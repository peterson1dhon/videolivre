use std::{
    env, fs, io,
    path::{Path, PathBuf},
    process::Stdio,
    sync::Arc,
    time::Duration,
};

use serde::Deserialize;
use tokio::{
    io::{AsyncBufReadExt, BufReader},
    process::Command,
    sync::watch,
    time::{Instant, interval, sleep},
};
use uuid::Uuid;

use crate::{
    Error,
    api::State,
    queue::{self, Job, Status},
};

const WORKER: &str = include_str!("../worker.py");
const LIMIT_TIME: Duration = Duration::from_secs(30 * 60);
const FORMATS: &str = "mov,mp4,m4a,3gp,3g2,mj2,matroska,webm,mp3,aac,mpegts,ogg,flv";
const EXTENSIONS: &[&str] = &[
    "mp4", "m4a", "mov", "webm", "mkv", "mp3", "aac", "ts", "ogg", "opus", "flv",
];

pub struct Tools {
    python: PathBuf,
    packages: PathBuf,
    ffmpeg: PathBuf,
}

impl Tools {
    pub fn load() -> Result<Self, Error> {
        fn executable(name: &str) -> Result<PathBuf, Error> {
            let value = env::var_os(name)
                .ok_or_else(|| format!("Configure {name} com o caminho completo do executável."))?;
            let path = PathBuf::from(value);
            if !path.is_absolute()
                || !path.is_file()
                || (cfg!(windows)
                    && !path
                        .extension()
                        .is_some_and(|ext| ext.eq_ignore_ascii_case("exe")))
            {
                return Err(format!("{name} precisa apontar para um executável local.").into());
            }
            Ok(path.canonicalize()?)
        }
        let packages = PathBuf::from(
            env::var_os("VLWEB_PYTHON_PACKAGES")
                .ok_or("Configure VLWEB_PYTHON_PACKAGES com a pasta do yt-dlp dedicado.")?,
        );
        if !packages.is_absolute() || !packages.join("yt_dlp/__init__.py").is_file() {
            return Err("yt-dlp não encontrado em VLWEB_PYTHON_PACKAGES.".into());
        }
        Ok(Self {
            python: executable("VLWEB_PYTHON")?,
            packages: packages.canonicalize()?,
            ffmpeg: executable("VLWEB_FFMPEG")?,
        })
    }
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum Event {
    Metadata {
        title: String,
        creator: String,
        site_id: String,
    },
    Progress {
        percent: Option<u8>,
    },
    Done {
        paths: Vec<String>,
    },
    Error {
        code: String,
    },
}

struct Failure(&'static str);

impl From<io::Error> for Failure {
    fn from(_: io::Error) -> Self {
        Self(
            "Falha ao acessar as ferramentas ou a pasta do serviço. Confira a instalação e o espaço livre.",
        )
    }
}

fn worker_error(code: &str) -> Failure {
    Failure(match code {
        "destination" => "O site direcionou o download para um endereço bloqueado.",
        "size" => "O item excede o espaço disponível para este download.",
        "drm" => "O vídeo tem proteção DRM.",
        "format" => "A qualidade pedida não está disponível. Tente outra qualidade ou áudio.",
        "playlist" => "Cole o link de um vídeo individual.",
        "unsupported" => "O extrator não reconheceu este link. Confira a URL.",
        "restricted" => "O site limitou o acesso ou exige login. Tente outro link público.",
        "network" => "Não foi possível falar com o site. Confira o link e tente de novo.",
        _ => {
            "O extrator não conseguiu baixar este vídeo. Confira se o link é público e se o yt-dlp está instalado."
        }
    })
}

pub async fn run_queue(state: Arc<State>) {
    loop {
        let next = start_next(&state);
        match next {
            Ok(Some((job, mut cancel))) => {
                let result = download(&state, &job, &mut cancel).await;
                finish(&state, job.id, result);
            }
            Ok(None) => state.wake.notified().await,
            Err(error) => {
                eprintln!("VideoLivre Web: fila indisponível ({:?})", error.kind());
                sleep(Duration::from_secs(2)).await;
            }
        }
    }
}

fn start_next(state: &State) -> io::Result<Option<(Job, watch::Receiver<bool>)>> {
    let mut queue = state.queue.lock().unwrap();
    let Some(index) = queue
        .jobs
        .iter()
        .position(|job| job.status == Status::Queued)
    else {
        return Ok(None);
    };
    let job = queue.change(|jobs| {
        let job = &mut jobs[index];
        job.status = Status::Running;
        job.stage = Some("extract".into());
        job.clone()
    })?;
    let (tx, rx) = watch::channel(false);
    *state.running.lock().unwrap() = Some((job.id, tx));
    Ok(Some((job, rx)))
}

fn note(state: &State, id: Uuid, event: Event) {
    let mut queue = state.queue.lock().unwrap();
    let Some(job) = queue
        .jobs
        .iter_mut()
        .find(|job| job.id == id && job.status == Status::Running)
    else {
        return;
    };
    match event {
        Event::Metadata {
            title,
            creator,
            site_id,
        } => {
            job.title = Some(queue::clean_text(&title, 240)).filter(|text| !text.is_empty());
            job.creator = queue::credit(&creator);
            job.site_id = site_id;
            job.stage = Some("download".into());
        }
        Event::Progress { percent } => {
            job.progress = percent.map(|p| p.min(99));
        }
        _ => (),
    }
}

fn finish(state: &State, id: Uuid, result: Result<PathBuf, Failure>) {
    let mut queue = state.queue.lock().unwrap();
    let mut running = state.running.lock().unwrap();
    let Some(index) = queue.jobs.iter().position(|job| job.id == id) else {
        *running = None;
        return;
    };
    let work = queue.work(id);
    let outcome = if queue.jobs[index].status == Status::Cancelling {
        Ok(None)
    } else {
        result.and_then(|source| publish(&queue.output(id), &source, &queue.jobs[index]).map(Some))
    };
    let completed = matches!(outcome, Ok(Some(_)));
    let apply_outcome = |jobs: &mut Vec<Job>| {
        let job = &mut jobs[index];
        job.stage = None;
        job.progress = None;
        match &outcome {
            Ok(Some(filename)) => {
                job.status = Status::Completed;
                job.progress = Some(100);
                job.filename = Some(filename.clone());
            }
            Ok(None) => job.status = Status::Cancelled,
            Err(Failure(message)) => {
                job.status = Status::Failed;
                job.error = Some((*message).into());
            }
        }
    };
    match queue.change(apply_outcome) {
        Ok(()) if completed => {
            if let Err(error) = fs::remove_dir_all(work) {
                eprintln!("VideoLivre Web: limpeza pendente ({:?})", error.kind());
            }
        }
        Err(error) => {
            eprintln!(
                "VideoLivre Web: resultado pendente de gravação ({:?})",
                error.kind()
            );
            apply_outcome(&mut queue.jobs);
        }
        _ => (),
    }
    *running = None;
}

fn publish(directory: &Path, source: &Path, job: &Job) -> Result<String, Failure> {
    let ext = source
        .extension()
        .and_then(|ext| ext.to_str())
        .ok_or(Failure("Formato de arquivo inesperado."))?;
    fs::create_dir_all(directory)?;
    let name = queue::filename(job, ext);
    let target = directory.join(&name);
    match fs::hard_link(source, &target) {
        Ok(()) => Ok(name),
        // A previous run can have published this exact item before saving its status.
        Err(error) if error.kind() == io::ErrorKind::AlreadyExists && target.is_file() => Ok(name),
        Err(error) => Err(error.into()),
    }
}

fn command(program: &Path, work: &Path) -> Command {
    let mut cmd = Command::new(program);
    cmd.env_clear()
        .current_dir(work)
        .kill_on_drop(true)
        .stdin(Stdio::null())
        .stderr(Stdio::null())
        .stdout(Stdio::piped())
        .env("TMP", work)
        .env("TEMP", work);
    if let Some(root) = env::var_os("SystemRoot") {
        cmd.env("SystemRoot", root);
    }
    #[cfg(windows)]
    cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    cmd
}

#[cfg(windows)]
fn supervise_windows(
    child: &tokio::process::Child,
) -> io::Result<std::os::windows::io::OwnedHandle> {
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_ACTIVE_PROCESS,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOB_OBJECT_LIMIT_PROCESS_MEMORY,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation,
        SetInformationJobObject,
    };
    let process = child
        .raw_handle()
        .ok_or_else(|| io::Error::other("processo sem handle"))?;
    // The job handle has one owner and is never inherited by the child.
    let raw = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
    if raw.is_null() {
        return Err(io::Error::last_os_error());
    }
    let job = unsafe { OwnedHandle::from_raw_handle(raw) };
    let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
    limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        | JOB_OBJECT_LIMIT_PROCESS_MEMORY;
    limits.BasicLimitInformation.ActiveProcessLimit = 1;
    limits.ProcessMemoryLimit = 768 * 1024 * 1024;
    // Both handles and the limits buffer remain live for these calls.
    unsafe {
        if SetInformationJobObject(
            job.as_raw_handle(),
            JobObjectExtendedLimitInformation,
            (&raw const limits).cast(),
            std::mem::size_of_val(&limits) as u32,
        ) == 0
            || AssignProcessToJobObject(job.as_raw_handle(), process) == 0
        {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(job)
}

struct Run<'a> {
    state: &'a State,
    id: Uuid,
    root: PathBuf,
    work: PathBuf,
    budget: u64,
    deadline: Instant,
    cancel: &'a mut watch::Receiver<bool>,
}

impl Run<'_> {
    async fn execute(&mut self, cmd: &mut Command) -> Result<Option<Vec<String>>, Failure> {
        if *self.cancel.borrow() {
            return Err(Failure("Download cancelado."));
        }
        let mut child = cmd.spawn()?;
        #[cfg(windows)]
        let _guard = supervise_windows(&child)?;
        let mut lines = BufReader::new(child.stdout.take().expect("stdout configurado")).lines();
        let mut paths = None;
        let mut problem = None;
        let mut check = interval(Duration::from_millis(200));
        let timeout = tokio::time::sleep_until(self.deadline);
        tokio::pin!(timeout);
        let result = loop {
            tokio::select! {
                _ = self.cancel.changed() => break Err(Failure("Download cancelado.")),
                _ = &mut timeout => break Err(Failure("O download passou do limite de 30 minutos.")),
                _ = check.tick() => {
                    match queue::within_budget(&self.root, &self.work, self.budget) {
                        Ok(true) => (),
                        Ok(false) => break Err(worker_error("size")),
                        Err(error) => break Err(error.into()),
                    }
                }
                line = lines.next_line() => {
                    match line {
                        Ok(Some(line)) => match serde_json::from_str(&line) {
                            Ok(Event::Done { paths: finished }) => paths = Some(finished),
                            Ok(Event::Error { code }) => problem = Some(worker_error(&code)),
                            Ok(event) => note(self.state, self.id, event),
                            Err(_) => (),
                        },
                        Ok(None) => {
                            break tokio::select! {
                                _ = self.cancel.changed() => Err(Failure("Download cancelado.")),
                                _ = &mut timeout => Err(Failure("O download passou do limite de 30 minutos.")),
                                exit = child.wait() => match exit {
                                    Ok(exit) if exit.success() => Ok(paths),
                                    Ok(_) => Err(problem.unwrap_or(Failure("A ferramenta falhou. Verifique a instalação ou tente outro formato."))),
                                    Err(error) => Err(error.into()),
                                }
                            };
                        }
                        Err(error) => break Err(error.into()),
                    }
                }
            }
        };
        if result.is_err() {
            let _ = child.kill().await;
        }
        result
    }
}

fn safe_input(work: &Path, path: &str) -> Result<String, Failure> {
    let error = Failure("O extrator retornou um arquivo inesperado.");
    let file = Path::new(path);
    let name = file
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(error)?;
    let Some((stem, ext)) = name.rsplit_once('.') else {
        return Err(Failure("Formato de arquivo inesperado."));
    };
    if !matches!(stem, "media.source" | "media.video" | "media.audio") || !EXTENSIONS.contains(&ext)
    {
        return Err(Failure("Formato de arquivo inesperado."));
    }
    let local = work.join(name);
    if !fs::symlink_metadata(&local)?.file_type().is_file() || fs::metadata(&local)?.len() == 0 {
        return Err(Failure("Arquivo parcial ou ausente."));
    }
    Ok(name.to_owned())
}

async fn download(
    state: &State,
    job: &Job,
    cancel: &mut watch::Receiver<bool>,
) -> Result<PathBuf, Failure> {
    let (root, work) = {
        let queue = state.queue.lock().unwrap();
        (queue.root.clone(), queue.work(job.id))
    };
    fs::create_dir_all(&work)?;
    for output in ["result.mp3", "result.mkv"] {
        match fs::remove_file(work.join(output)) {
            Err(error) if error.kind() != io::ErrorKind::NotFound => return Err(error.into()),
            _ => (),
        }
    }
    let budget = queue::space_for_job(&root, &work)?;
    if budget < 1024 * 1024 || !queue::within_budget(&root, &work, budget)? {
        return Err(worker_error("size"));
    }
    let mut run = Run {
        state,
        id: job.id,
        root,
        work: work.clone(),
        budget,
        deadline: Instant::now() + LIMIT_TIME,
        cancel,
    };
    let mut python = command(&state.tools.python, &work);
    python
        .args([
            "-I",
            "-S",
            "-c",
            WORKER,
            &job.url,
            job.quality.argument(),
            &budget.to_string(),
        ])
        .arg(&state.tools.packages);
    let paths = run
        .execute(&mut python)
        .await?
        .ok_or(Failure("O extrator não retornou um arquivo."))?;
    if !queue::within_budget(&run.root, &work, budget)? {
        return Err(worker_error("size"));
    }
    let files = paths
        .iter()
        .map(|path| safe_input(&work, path))
        .collect::<Result<Vec<_>, _>>()?;
    let mp3 = job.quality == queue::Quality::Mp3;
    if let [source] = files.as_slice()
        && !mp3
        && source.starts_with("media.source.")
    {
        return Ok(work.join(source));
    }
    if !matches!(files.as_slice(), [one] if mp3 && one.starts_with("media.source."))
        && !matches!(files.as_slice(), [video, audio] if !mp3 && video.starts_with("media.video.") && audio.starts_with("media.audio."))
    {
        return Err(Failure(
            "O extrator retornou uma combinação de formatos inesperada.",
        ));
    }
    {
        let mut queue = state.queue.lock().unwrap();
        if let Some(item) = queue
            .jobs
            .iter_mut()
            .find(|item| item.id == job.id && item.status == Status::Running)
        {
            item.stage = Some("convert".into());
            item.progress = None;
        }
    }
    let output = if mp3 { "result.mp3" } else { "result.mkv" };
    let mut ffmpeg = command(&state.tools.ffmpeg, &work);
    ffmpeg.args(["-hide_banner", "-nostdin", "-loglevel", "error", "-n"]);
    for name in &files {
        ffmpeg.args([
            "-protocol_whitelist",
            "file,pipe",
            "-format_whitelist",
            FORMATS,
            "-i",
            name,
        ]);
    }
    if mp3 {
        ffmpeg.args(["-map", "0:a:0", "-vn", "-c:a", "libmp3lame", "-q:a", "2"]);
    } else {
        ffmpeg.args(["-map", "0:v:0", "-map", "1:a:0", "-c", "copy"]);
    }
    let used = queue::size_on_disk(&work)?;
    let output_limit = budget.saturating_sub(used);
    if output_limit < 1024 * 1024 {
        return Err(worker_error("size"));
    }
    ffmpeg.args([
        "-map_metadata",
        "-1",
        "-map_chapters",
        "-1",
        "-fs",
        &output_limit.to_string(),
        output,
    ]);
    run.execute(&mut ffmpeg).await?;
    let file = work.join(output);
    let size = fs::metadata(&file)?.len();
    if size == 0
        || size >= output_limit.saturating_sub(256 * 1024)
        || !queue::within_budget(&run.root, &work, budget)?
    {
        return Err(worker_error("size"));
    }
    Ok(file)
}

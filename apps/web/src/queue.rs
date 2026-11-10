use std::{
    fs, io,
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const MAX_JOBS: usize = 60;
pub const MAX_ACTIVE: usize = 12;
pub const MAX_JOB_BYTES: u64 = 512 * 1024 * 1024;
const MAX_STORAGE: u64 = 10 * 1024 * 1024 * 1024;
const RESERVE: u64 = 1024 * 1024 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum Quality {
    #[serde(rename = "best")]
    Best,
    #[serde(rename = "1080")]
    Hd1080,
    #[serde(rename = "720")]
    Hd720,
    #[serde(rename = "480")]
    Sd480,
    #[serde(rename = "mp3")]
    Mp3,
}

impl Quality {
    pub fn argument(self) -> &'static str {
        match self {
            Self::Best => "best",
            Self::Hd1080 => "1080",
            Self::Hd720 => "720",
            Self::Sd480 => "480",
            Self::Mp3 => "mp3",
        }
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Queued,
    Running,
    Cancelling,
    Cancelled,
    Failed,
    Completed,
}

impl Status {
    pub fn active(self) -> bool {
        matches!(self, Self::Queued | Self::Running | Self::Cancelling)
    }
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Job {
    pub id: Uuid,
    pub url: String,
    pub quality: Quality,
    pub credit: Option<String>,
    pub title: Option<String>,
    pub creator: Option<String>,
    pub status: Status,
    pub stage: Option<String>,
    pub progress: Option<u8>,
    pub error: Option<String>,
    pub filename: Option<String>,
    pub created_at: u64,
    #[serde(skip)]
    pub site_id: String,
}

impl Job {
    pub fn new(url: String, quality: Quality, credit: Option<String>) -> Self {
        Self {
            id: Uuid::new_v4(),
            url,
            quality,
            credit,
            title: None,
            creator: None,
            status: Status::Queued,
            stage: None,
            progress: None,
            error: None,
            filename: None,
            created_at: SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
            site_id: String::new(),
        }
    }
}

pub struct Queue {
    pub root: PathBuf,
    pub jobs: Vec<Job>,
}

impl Queue {
    pub fn open(root: PathBuf) -> io::Result<Self> {
        fs::create_dir_all(root.join("work"))?;
        fs::create_dir_all(root.join("downloads"))?;
        let jobs = match fs::read(root.join("queue.json")) {
            Ok(bytes) => serde_json::from_slice(&bytes).map_err(io::Error::other)?,
            Err(error) if error.kind() == io::ErrorKind::NotFound => Vec::new(),
            Err(error) => return Err(error),
        };
        let mut queue = Self { root, jobs };
        for job in &mut queue.jobs {
            if matches!(job.status, Status::Running | Status::Cancelling) {
                job.status = Status::Cancelled;
                job.stage = None;
                job.progress = None;
            }
        }
        queue.save()?;
        Ok(queue)
    }

    pub fn save(&self) -> io::Result<()> {
        let mut file = tempfile::NamedTempFile::new_in(&self.root)?;
        serde_json::to_writer(&mut file, &self.jobs)?;
        file.as_file().sync_all()?;
        file.persist(self.root.join("queue.json"))?;
        Ok(())
    }

    pub fn change<T>(&mut self, edit: impl FnOnce(&mut Vec<Job>) -> T) -> io::Result<T> {
        let before = self.jobs.clone();
        let value = edit(&mut self.jobs);
        if let Err(error) = self.save() {
            self.jobs = before;
            return Err(error);
        }
        Ok(value)
    }

    pub fn work(&self, id: Uuid) -> PathBuf {
        self.root.join("work").join(id.to_string())
    }

    pub fn output(&self, id: Uuid) -> PathBuf {
        self.root.join("downloads").join(id.to_string())
    }
}

pub fn size_on_disk(path: &Path) -> io::Result<u64> {
    let mut bytes = 0u64;
    for item in fs::read_dir(path)? {
        let item = item?;
        let kind = item.file_type()?;
        if kind.is_dir() {
            bytes = bytes.saturating_add(size_on_disk(&item.path())?);
        } else if kind.is_file() {
            bytes = bytes.saturating_add(item.metadata()?.len());
        }
    }
    Ok(bytes)
}

pub fn space_for_job(root: &Path, work: &Path) -> io::Result<u64> {
    let remaining = MAX_STORAGE
        .saturating_sub(size_on_disk(&root.join("downloads"))?)
        .saturating_sub(size_on_disk(&root.join("work"))?)
        .saturating_add(size_on_disk(work)?);
    let free = fs2::available_space(root)?.saturating_sub(RESERVE);
    Ok(remaining.min(MAX_JOB_BYTES).min(free))
}

pub fn within_budget(root: &Path, work: &Path, budget: u64) -> io::Result<bool> {
    Ok(size_on_disk(work)? < budget && fs2::available_space(root)? >= RESERVE)
}

pub fn clean_text(text: &str, max_chars: usize) -> String {
    let clean: String = text
        .chars()
        .filter(|ch| {
            !ch.is_control() && !matches!(ch, '\u{202a}'..='\u{202e}' | '\u{2066}'..='\u{2069}')
        })
        .map(|ch| if "<>:\"/\\|?*".contains(ch) { ' ' } else { ch })
        .take(max_chars)
        .collect();
    clean
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches(['.', ' '])
        .to_owned()
}

pub fn credit(text: &str) -> Option<String> {
    let cleaned = clean_text(text.trim().trim_start_matches('@'), 64);
    (!cleaned.is_empty()).then(|| format!("@{cleaned}"))
}

pub fn filename(job: &Job, ext: &str) -> String {
    let raw = job.title.as_deref().unwrap_or_default();
    let mut title = raw.to_owned();
    let site_id = &job.site_id;
    if !site_id.is_empty() && site_id.bytes().all(|byte| byte.is_ascii_digit()) {
        if title.trim() == site_id {
            title.clear();
        } else if site_id.len() >= 6 {
            title = title
                .replace(&format!("[{site_id}]"), "")
                .replace(site_id, "");
        }
    }
    let mut title = clean_text(&title, 96);
    if title.is_empty() {
        title = "Vídeo".to_owned();
    }
    let stem = title
        .split('.')
        .next()
        .unwrap_or_default()
        .trim_end()
        .to_ascii_uppercase();
    if matches!(
        stem.as_str(),
        "CON" | "PRN" | "AUX" | "NUL" | "CONIN$" | "CONOUT$"
    ) || (stem.starts_with("COM") || stem.starts_with("LPT"))
        && stem.chars().count() == 4
        && stem
            .chars()
            .last()
            .is_some_and(|ch| ch.is_ascii_digit() || "¹²³".contains(ch))
    {
        title.insert(0, '_');
    }
    let author = job.credit.as_ref().or(job.creator.as_ref());
    let mut units = author.map_or(0, |credit| credit.encode_utf16().count());
    title = title
        .chars()
        .take_while(|ch| {
            units += ch.len_utf16();
            units <= 220
        })
        .collect();
    match author {
        Some(author) => format!("{title} [{author}].{ext}"),
        None => format!("{title}.{ext}"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn filename_prefers_manual_credit_and_excludes_site_id() {
        let mut job = Job::new(
            "https://example.com/".into(),
            Quality::Best,
            credit(" @João Vídeos "),
        );
        job.title = Some("Amor: ação [1234567890]".into());
        job.site_id = "1234567890".into();
        job.creator = credit("Outra pessoa");
        assert_eq!(filename(&job, "mp4"), "Amor ação [@João Vídeos].mp4");
        job.credit = None;
        job.title = Some("CON.txt".into());
        assert_eq!(filename(&job, "mp4"), "_CON.txt [@Outra pessoa].mp4");
    }

    #[test]
    fn reopening_retains_history_and_marks_interrupted_work_for_resume() {
        let dir = tempfile::tempdir().unwrap();
        let mut queue = Queue::open(dir.path().to_owned()).unwrap();
        let mut job = Job::new("https://example.com/".into(), Quality::Mp3, None);
        job.status = Status::Running;
        job.stage = Some("download".into());
        queue.change(|jobs| jobs.push(job)).unwrap();
        let reopened = Queue::open(dir.path().to_owned()).unwrap();
        assert_eq!(reopened.jobs[0].status, Status::Cancelled);
        assert_eq!(reopened.jobs[0].stage, None);
    }
}

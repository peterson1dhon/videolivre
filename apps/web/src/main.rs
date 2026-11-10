#![cfg_attr(all(windows, not(debug_assertions)), windows_subsystem = "windows")]

mod api;
mod download;
mod queue;

use std::{
    env, fs,
    io::Write,
    net::Ipv4Addr,
    path::{Path, PathBuf},
    sync::Arc,
};

use fs2::FileExt;
use tokio::net::TcpListener;

type Error = Box<dyn std::error::Error + Send + Sync>;

fn random_key() -> String {
    use rand::TryRngCore;
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng
        .try_fill_bytes(&mut bytes)
        .expect("entropia do sistema indisponível");
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn read_key(root: &Path) -> Result<String, Error> {
    let path = root.join("chave.txt");
    if !path.exists() {
        let mut tmp = tempfile::NamedTempFile::new_in(root)?;
        writeln!(tmp, "{}", random_key())?;
        tmp.as_file().sync_all()?;
        tmp.persist_noclobber(&path)?;
    }
    let key = fs::read_to_string(path)?.trim().to_owned();
    if key.len() != 64 || !key.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(
            "chave.txt inválida. Com o servidor parado, mova o arquivo para gerar outra chave."
                .into(),
        );
    }
    Ok(key)
}

fn data_directory() -> Option<PathBuf> {
    env::var_os("VLWEB_DATA").map(PathBuf::from).or_else(|| {
        env::var_os("LOCALAPPDATA").map(|base| PathBuf::from(base).join("VideoLivreWeb"))
    })
}

#[tokio::main]
async fn main() {
    let Some(root) = data_directory().filter(|path| path.is_absolute()) else {
        eprintln!("Configure LOCALAPPDATA ou VLWEB_DATA com um caminho absoluto.");
        std::process::exit(1);
    };
    if let Err(error) = run(&root).await {
        eprintln!("VideoLivre Web: {error}");
        let _ = fs::create_dir_all(&root);
        let _ = fs::write(root.join("erro-inicializacao.txt"), format!("{error}\n"));
        std::process::exit(1);
    }
}

async fn run(root: &Path) -> Result<(), Error> {
    fs::create_dir_all(root)?;
    let root = root.canonicalize()?;
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .write(true)
        .open(root.join("server.lock"))?;
    FileExt::try_lock_exclusive(&lock)
        .map_err(|_| "Outra instância está usando esta pasta de dados.")?;
    let key = read_key(&root)?;
    let tools = download::Tools::load()?;
    let port = env::var("VLWEB_PORT")
        .unwrap_or_else(|_| "8787".to_owned())
        .parse::<u16>()?;
    let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, port)).await?;
    let state = Arc::new(api::State::new(
        key,
        queue::Queue::open(root.clone())?,
        tools,
    ));
    let worker = tokio::spawn(download::run_queue(state.clone()));
    let _ = fs::remove_file(root.join("erro-inicializacao.txt"));
    println!(
        "VideoLivre Web {} em http://localhost:{}",
        env!("CARGO_PKG_VERSION"),
        listener.local_addr()?.port()
    );
    let result = axum::serve(listener, api::router(state))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await;
    worker.abort();
    result?;
    Ok(())
}

use std::{
    collections::HashMap,
    fs, io,
    net::IpAddr,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};

use axum::{
    Json, Router,
    body::Body,
    extract::{DefaultBodyLimit, Path, Request, State as AppState},
    http::{HeaderMap, HeaderValue, StatusCode, header},
    middleware::{self, Next},
    response::{Html, IntoResponse, Response},
    routing::{delete, get, post},
};
use percent_encoding::{NON_ALPHANUMERIC, utf8_percent_encode};
use serde::Deserialize;
use serde_json::json;
use subtle::ConstantTimeEq;
use tokio::sync::{Notify, watch};
use tower::ServiceExt;
use tower_http::services::ServeFile;
use url::{Host, Url};
use uuid::Uuid;

use crate::{
    download::Tools,
    queue::{self, Job, MAX_ACTIVE, MAX_JOBS, Quality, Queue, Status},
    random_key,
};

const COOKIE: &str = "vlweb_session";
const SESSION_AGE: Duration = Duration::from_secs(12 * 60 * 60);
const LOGIN_LIMIT: u8 = 12;

pub struct State {
    pub queue: Mutex<Queue>,
    pub tools: Tools,
    pub wake: Notify,
    pub running: Mutex<Option<(Uuid, watch::Sender<bool>)>>,
    key: String,
    sessions: Mutex<Sessions>,
}

struct Sessions {
    tokens: HashMap<String, Instant>,
    window: Instant,
    attempts: u8,
}

impl State {
    pub fn new(key: String, queue: Queue, tools: Tools) -> Self {
        Self {
            queue: Mutex::new(queue),
            tools,
            wake: Notify::new(),
            running: Mutex::new(None),
            key,
            sessions: Mutex::new(Sessions {
                tokens: HashMap::new(),
                window: Instant::now(),
                attempts: 0,
            }),
        }
    }
}

#[derive(Debug)]
struct ApiError(StatusCode, &'static str);

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.0, Json(json!({"error": self.1}))).into_response()
    }
}

impl From<io::Error> for ApiError {
    fn from(error: io::Error) -> Self {
        eprintln!("VideoLivre Web: erro de armazenamento ({:?})", error.kind());
        Self(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Falha ao gravar os dados do servidor.",
        )
    }
}

const UNAUTHORIZED: ApiError = ApiError(StatusCode::UNAUTHORIZED, "Entre com a chave do servidor.");
const NOT_FOUND: ApiError = ApiError(StatusCode::NOT_FOUND, "Item ou arquivo indisponível.");
const CONFLICT: ApiError = ApiError(
    StatusCode::CONFLICT,
    "A ação não está disponível neste estado.",
);

type Result<T> = std::result::Result<T, ApiError>;

pub fn router(state: Arc<State>) -> Router {
    let protected = Router::new()
        .route("/jobs", get(list).post(add).delete(clear))
        .route("/jobs/{id}", delete(remove))
        .route("/jobs/{id}/cancel", post(cancel))
        .route("/jobs/{id}/resume", post(resume))
        .route("/jobs/{id}/file", get(file))
        .route("/session", delete(logout))
        .route_layer(middleware::from_fn_with_state(state.clone(), authorize));
    Router::new()
        .route(
            "/",
            get(|| async { Html(include_str!("../static/index.html")) }),
        )
        .route(
            "/app.css",
            get(|| async { asset("text/css; charset=utf-8", include_str!("../static/app.css")) }),
        )
        .route(
            "/app.js",
            get(|| async {
                asset(
                    "text/javascript; charset=utf-8",
                    include_str!("../static/app.js"),
                )
            }),
        )
        .route(
            "/icon.svg",
            get(|| async { asset("image/svg+xml", include_str!("../static/icon.svg")) }),
        )
        .route(
            "/icon-192.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    include_bytes!("../static/icon-192.png").as_slice(),
                )
            }),
        )
        .route(
            "/icon-512.png",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "image/png")],
                    include_bytes!("../static/icon-512.png").as_slice(),
                )
            }),
        )
        .route(
            "/manifest.webmanifest",
            get(|| async {
                asset(
                    "application/manifest+json",
                    include_str!("../static/manifest.webmanifest"),
                )
            }),
        )
        .route(
            "/api/v1/info",
            get(|| async { Json(json!({"version": env!("CARGO_PKG_VERSION"), "api": "v1"})) }),
        )
        .route("/api/v1/session", post(login))
        .nest("/api/v1", protected)
        .layer(DefaultBodyLimit::max(8 * 1024))
        .layer(middleware::from_fn(security_headers))
        .with_state(state)
}

fn asset(content_type: &'static str, text: &'static str) -> impl IntoResponse {
    ([(header::CONTENT_TYPE, content_type)], text)
}

async fn security_headers(req: Request, next: Next) -> Response {
    let mut response = next.run(req).await;
    let headers = response.headers_mut();
    for (name, value) in [
        ("cache-control", "no-store"),
        (
            "content-security-policy",
            "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; manifest-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
        ),
        ("x-content-type-options", "nosniff"),
        ("referrer-policy", "no-referrer"),
        ("cross-origin-resource-policy", "same-origin"),
        (
            "permissions-policy",
            "camera=(), microphone=(), geolocation=()",
        ),
    ] {
        headers.insert(name, HeaderValue::from_static(value));
    }
    response
}

fn same_origin_action(headers: &HeaderMap) -> bool {
    // A cross-origin browser cannot set this header without a successful CORS preflight.
    headers
        .get("x-videolivre")
        .is_some_and(|value| value == "1")
}

fn session_cookie(headers: &HeaderMap) -> Option<&str> {
    headers
        .get(header::COOKIE)?
        .to_str()
        .ok()?
        .split(';')
        .find_map(|pair| {
            let (name, value) = pair.trim().split_once('=')?;
            (name == COOKIE).then_some(value)
        })
}

fn cookie(value: &str, age: u64) -> String {
    format!("{COOKIE}={value}; Path=/; Max-Age={age}; HttpOnly; Secure; SameSite=Strict")
}

fn key_matches(key: &str, supplied: &str) -> bool {
    key.as_bytes().ct_eq(supplied.as_bytes()).into()
}

async fn authorize(
    AppState(state): AppState<Arc<State>>,
    req: Request,
    next: Next,
) -> Result<Response> {
    if let Some(auth) = req.headers().get(header::AUTHORIZATION) {
        if auth
            .to_str()
            .ok()
            .and_then(|s| s.strip_prefix("Bearer "))
            .is_some_and(|token| key_matches(&state.key, token))
        {
            return Ok(next.run(req).await);
        }
        return Err(UNAUTHORIZED);
    }
    let valid = session_cookie(req.headers()).is_some_and(|token| {
        state
            .sessions
            .lock()
            .unwrap()
            .tokens
            .get(token)
            .is_some_and(|until| *until > Instant::now())
    });
    if !valid {
        return Err(UNAUTHORIZED);
    }
    if !matches!(
        *req.method(),
        axum::http::Method::GET | axum::http::Method::HEAD
    ) && !same_origin_action(req.headers())
    {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "Cabeçalho da sessão ausente.",
        ));
    }
    Ok(next.run(req).await)
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Login {
    key: String,
}

async fn login(
    AppState(state): AppState<Arc<State>>,
    headers: HeaderMap,
    Json(body): Json<Login>,
) -> Result<impl IntoResponse> {
    if !same_origin_action(&headers) {
        return Err(ApiError(
            StatusCode::FORBIDDEN,
            "Cabeçalho da sessão ausente.",
        ));
    }
    let now = Instant::now();
    let mut sessions = state.sessions.lock().unwrap();
    if now.duration_since(sessions.window) >= Duration::from_secs(60) {
        sessions.window = now;
        sessions.attempts = 0;
    }
    if sessions.attempts >= LOGIN_LIMIT {
        return Err(ApiError(
            StatusCode::TOO_MANY_REQUESTS,
            "Aguarde um minuto antes de tentar novamente.",
        ));
    }
    if !key_matches(&state.key, body.key.trim()) {
        sessions.attempts += 1;
        return Err(UNAUTHORIZED);
    }
    sessions.tokens.retain(|_, until| *until > now);
    if let Some(old) = session_cookie(&headers) {
        sessions.tokens.remove(old);
    }
    if sessions.tokens.len() >= 16
        && let Some(oldest) = sessions
            .tokens
            .iter()
            .min_by_key(|(_, until)| *until)
            .map(|(key, _)| key.clone())
    {
        sessions.tokens.remove(&oldest);
    }
    let token = random_key();
    sessions.tokens.insert(token.clone(), now + SESSION_AGE);
    Ok((
        StatusCode::NO_CONTENT,
        [(header::SET_COOKIE, cookie(&token, SESSION_AGE.as_secs()))],
    ))
}

async fn logout(AppState(state): AppState<Arc<State>>, headers: HeaderMap) -> impl IntoResponse {
    if let Some(token) = session_cookie(&headers) {
        state.sessions.lock().unwrap().tokens.remove(token);
    }
    (
        StatusCode::NO_CONTENT,
        [(header::SET_COOKIE, cookie("", 0))],
    )
}

async fn list(AppState(state): AppState<Arc<State>>) -> Json<Vec<Job>> {
    Json(state.queue.lock().unwrap().jobs.clone())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct NewJob {
    url: String,
    quality: Quality,
    credit: Option<String>,
}

fn validated_url(raw: &str) -> Result<String> {
    const INVALID: ApiError = ApiError(
        StatusCode::BAD_REQUEST,
        "Use um link público HTTP ou HTTPS, sem usuário, senha ou porta personalizada.",
    );
    let raw = raw.trim();
    if raw.len() > 4096 || raw.chars().any(char::is_control) {
        return Err(INVALID);
    }
    let url = Url::parse(raw).map_err(|_| INVALID)?;
    if !matches!(url.scheme(), "http" | "https")
        || !url.username().is_empty()
        || url.password().is_some()
        || !matches!(url.port_or_known_default(), Some(80 | 443))
    {
        return Err(INVALID);
    }
    match url.host() {
        Some(Host::Domain(name)) => {
            let name = name.trim_end_matches('.');
            if !name.contains('.')
                || [
                    ".localhost",
                    ".local",
                    ".internal",
                    ".test",
                    ".invalid",
                    ".home.arpa",
                ]
                .iter()
                .any(|suffix| name.ends_with(suffix))
            {
                return Err(INVALID);
            }
        }
        Some(Host::Ipv4(addr)) if obvious_public(IpAddr::V4(addr)) => (),
        Some(Host::Ipv6(addr)) if obvious_public(IpAddr::V6(addr)) => (),
        _ => return Err(INVALID),
    }
    Ok(url.to_string())
}

fn obvious_public(addr: IpAddr) -> bool {
    match addr {
        IpAddr::V4(a) => {
            let [first, second, third, _] = a.octets();
            !a.is_private()
                && !a.is_loopback()
                && !a.is_link_local()
                && !a.is_documentation()
                && !matches!(first, 0 | 224..=255)
                && !matches!((first, second), (100, 64..=127) | (198, 18..=19))
                && !matches!((first, second, third), (192, 0, 0) | (192, 88, 99))
        }
        IpAddr::V6(a) => {
            let [first, second, ..] = a.segments();
            (0x2000..=0x3fff).contains(&first)
                && !matches!(
                    (first, second),
                    (0x2001, 0..=0x1ff | 0xdb8) | (0x2002, _) | (0x3fff, 0..=0x0fff)
                )
        }
    }
}

fn ensure_capacity(queue: &Queue) -> Result<()> {
    if queue.jobs.iter().filter(|job| job.status.active()).count() >= MAX_ACTIVE {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "A fila já tem 12 itens ativos. Aguarde ou cancele um item.",
        ));
    }
    Ok(())
}

async fn add(
    AppState(state): AppState<Arc<State>>,
    Json(body): Json<NewJob>,
) -> Result<(StatusCode, Json<Job>)> {
    let url = validated_url(&body.url)?;
    let credit = match body
        .credit
        .as_deref()
        .map(str::trim)
        .filter(|text| !text.is_empty())
    {
        Some(text) if text.chars().count() <= 65 => Some(queue::credit(text).ok_or(ApiError(
            StatusCode::BAD_REQUEST,
            "Informe um crédito válido.",
        ))?),
        Some(_) => {
            return Err(ApiError(
                StatusCode::BAD_REQUEST,
                "O crédito pode ter até 64 caracteres e um @.",
            ));
        }
        None => None,
    };
    let mut queue = state.queue.lock().unwrap();
    ensure_capacity(&queue)?;
    if queue.jobs.len() >= MAX_JOBS {
        return Err(ApiError(
            StatusCode::CONFLICT,
            "O histórico atingiu 60 itens. Limpe o histórico para continuar.",
        ));
    }
    let job = Job::new(url, body.quality, credit);
    queue.change(|jobs| jobs.push(job.clone()))?;
    state.wake.notify_one();
    Ok((StatusCode::CREATED, Json(job)))
}

async fn cancel(AppState(state): AppState<Arc<State>>, Path(id): Path<Uuid>) -> Result<StatusCode> {
    let mut queue = state.queue.lock().unwrap();
    let index = queue
        .jobs
        .iter()
        .position(|j| j.id == id)
        .ok_or(NOT_FOUND)?;
    let next = match queue.jobs[index].status {
        Status::Queued => Status::Cancelled,
        Status::Running => Status::Cancelling,
        Status::Cancelling | Status::Cancelled => return Ok(StatusCode::NO_CONTENT),
        _ => return Err(CONFLICT),
    };
    queue.change(|jobs| {
        jobs[index].status = next;
        jobs[index].stage = None;
        jobs[index].progress = None;
    })?;
    if let Some((running, signal)) = state.running.lock().unwrap().as_ref()
        && *running == id
    {
        let _ = signal.send(true);
    }
    Ok(StatusCode::NO_CONTENT)
}

async fn resume(AppState(state): AppState<Arc<State>>, Path(id): Path<Uuid>) -> Result<StatusCode> {
    let mut queue = state.queue.lock().unwrap();
    let index = queue
        .jobs
        .iter()
        .position(|j| j.id == id)
        .ok_or(NOT_FOUND)?;
    match queue.jobs[index].status {
        Status::Queued | Status::Running => return Ok(StatusCode::NO_CONTENT),
        Status::Cancelled | Status::Failed => (),
        _ => return Err(CONFLICT),
    }
    ensure_capacity(&queue)?;
    queue.change(|jobs| {
        let mut job = jobs.remove(index);
        job.status = Status::Queued;
        job.error = None;
        job.progress = None;
        jobs.push(job);
    })?;
    state.wake.notify_one();
    Ok(StatusCode::NO_CONTENT)
}

fn discard_partial(queue: &Queue, id: Uuid) -> io::Result<()> {
    match fs::remove_dir_all(queue.work(id)) {
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        result => result,
    }
}

async fn remove(AppState(state): AppState<Arc<State>>, Path(id): Path<Uuid>) -> Result<StatusCode> {
    let mut queue = state.queue.lock().unwrap();
    let index = queue
        .jobs
        .iter()
        .position(|j| j.id == id)
        .ok_or(NOT_FOUND)?;
    if queue.jobs[index].status.active() {
        return Err(CONFLICT);
    }
    discard_partial(&queue, id)?;
    queue.change(|jobs| jobs.remove(index))?;
    Ok(StatusCode::NO_CONTENT)
}

async fn clear(AppState(state): AppState<Arc<State>>) -> Result<StatusCode> {
    let mut queue = state.queue.lock().unwrap();
    for job in queue.jobs.iter().filter(|job| !job.status.active()) {
        discard_partial(&queue, job.id)?;
    }
    queue.change(|jobs| jobs.retain(|job| job.status.active()))?;
    Ok(StatusCode::NO_CONTENT)
}

async fn file(
    AppState(state): AppState<Arc<State>>,
    Path(id): Path<Uuid>,
    req: Request,
) -> Result<Response> {
    let (directory, name) = {
        let queue = state.queue.lock().unwrap();
        let job = queue
            .jobs
            .iter()
            .find(|job| job.id == id && job.status == Status::Completed)
            .ok_or(NOT_FOUND)?;
        (queue.output(id), job.filename.clone().ok_or(NOT_FOUND)?)
    };
    if name.contains(['/', '\\', ':']) || matches!(name.as_str(), "" | "." | "..") {
        return Err(NOT_FOUND);
    }
    let path = directory.join(&name);
    let canonical_dir = tokio::fs::canonicalize(&directory)
        .await
        .map_err(|_| NOT_FOUND)?;
    let canonical = tokio::fs::canonicalize(&path)
        .await
        .map_err(|_| NOT_FOUND)?;
    if canonical_dir != directory
        || canonical.parent() != Some(canonical_dir.as_path())
        || !tokio::fs::symlink_metadata(&path)
            .await
            .is_ok_and(|info| info.file_type().is_file())
    {
        return Err(NOT_FOUND);
    }
    let result = ServeFile::new(canonical)
        .oneshot(req.map(|_| Body::empty()))
        .await
        .expect("ServeFile returns an HTTP error response")
        .into_response();
    let mut result = result;
    let ext = name.rsplit_once('.').map_or("bin", |(_, ext)| ext);
    let safe_ext = if ext.bytes().all(|b| b.is_ascii_alphanumeric()) {
        ext
    } else {
        "bin"
    };
    let disposition = format!(
        "attachment; filename=\"VideoLivre.{safe_ext}\"; filename*=UTF-8''{}",
        utf8_percent_encode(&name, NON_ALPHANUMERIC)
    );
    result.headers_mut().insert(
        header::CONTENT_DISPOSITION,
        HeaderValue::from_str(&disposition).map_err(|_| NOT_FOUND)?,
    );
    result.headers_mut().insert(
        header::CONTENT_TYPE,
        HeaderValue::from_static("application/octet-stream"),
    );
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_public_web_urls_and_rejects_local_obfuscated_targets() {
        assert_eq!(
            validated_url(" https://media.example.com/ação ").unwrap(),
            "https://media.example.com/a%C3%A7%C3%A3o"
        );
        for blocked in [
            "file:///x",
            "http://2130706433",
            "http://0x7f.1",
            "http://[::ffff:127.0.0.1]",
            "http://[64:ff9b::7f00:1]",
            "http://100.100.100.100",
            "http://a.local",
            "http://x.home.arpa",
            "https://user:pass@example.com",
            "http://example.com:8787",
            "http://169.254.169.254",
        ] {
            assert!(validated_url(blocked).is_err(), "{blocked}");
        }
    }
}

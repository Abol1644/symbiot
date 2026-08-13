#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, mpsc};
use std::sync::mpsc::{Receiver, RecvTimeoutError, Sender};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, State};

const MAX_SIDECAR_RESTARTS: u32 = 3;
const DEFAULT_SIDECAR_CMD: &str =
    "uv run uvicorn symbiot.sidecar:app --host 127.0.0.1 --port 8100";
const DEFAULT_SIDECAR_URL: &str = "http://127.0.0.1:8100";
const TOKEN_MARKER: &str = "sidecar API token: ";

#[derive(Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
enum SidecarLifecycle {
    Running,
    Stopped,
    Restarting,
}

impl SidecarLifecycle {
    fn as_str(self) -> &'static str {
        match self {
            SidecarLifecycle::Running => "running",
            SidecarLifecycle::Stopped => "stopped",
            SidecarLifecycle::Restarting => "restarting",
        }
    }
}

/// Shared sidecar supervision state.  The supervisor thread owns the Child;
/// everything else lives here so commands can query and signal it.
struct SidecarState {
    lifecycle: Mutex<SidecarLifecycle>,
    token: Mutex<Option<String>>,
    child_pid: Mutex<Option<u32>>,
    restarts: Mutex<u32>,
    stopping: AtomicBool,
    supervisor: AtomicBool,
}

impl SidecarState {
    fn new() -> Self {
        Self {
            lifecycle: Mutex::new(SidecarLifecycle::Stopped),
            token: Mutex::new(None),
            child_pid: Mutex::new(None),
            restarts: Mutex::new(0),
            stopping: AtomicBool::new(false),
            supervisor: AtomicBool::new(false),
        }
    }
}

// ---------------------------------------------------------------------------
// Process helpers
// ---------------------------------------------------------------------------

/// Minimal shlex-style splitter (double quotes and backslash escapes).
fn split_command(line: &str) -> Vec<String> {
    let mut args = Vec::new();
    let mut current = String::new();
    let mut chars = line.trim().chars().peekable();
    let mut in_quote = false;
    while let Some(ch) = chars.next() {
        match ch {
            '"' => in_quote = !in_quote,
            ' ' | '\t' if !in_quote => {
                if !current.is_empty() {
                    args.push(std::mem::take(&mut current));
                }
            }
            '\\' => {
                if let Some(next) = chars.next() {
                    current.push(next);
                } else {
                    current.push('\\');
                }
            }
            _ => current.push(ch),
        }
    }
    if !current.is_empty() {
        args.push(current);
    }
    args
}

fn find_backend_dir() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    for dir in cwd.ancestors() {
        if dir.join("src").join("symbiot").join("sidecar.py").is_file() {
            return Some(dir.to_path_buf());
        }
        if dir.join("backend").join("src").join("symbiot").join("sidecar.py").is_file() {
            return Some(dir.join("backend"));
        }
    }
    None
}

fn sidecar_plugin_config(app: &AppHandle) -> Option<&serde_json::Value> {
    app.config().plugins.0.get("sidecar")
}

fn sidecar_config(app: &AppHandle) -> (Vec<String>, Option<PathBuf>) {
    let mut command = std::env::var("SYMBIOT_SIDECAR_CMD")
        .unwrap_or_else(|_| DEFAULT_SIDECAR_CMD.to_string());
    let mut workdir: Option<PathBuf> = std::env::var("SYMBIOT_SIDECAR_DIR").ok().map(PathBuf::from);
    if let Some(value) = sidecar_plugin_config(app) {
        if let Some(cmd) = value.get("command").and_then(|v| v.as_str()) {
            if !cmd.trim().is_empty() {
                command = cmd.trim().to_string();
            }
        }
        if let Some(dir) = value.get("workdir").and_then(|v| v.as_str()) {
            if !dir.trim().is_empty() {
                workdir = Some(PathBuf::from(dir.trim()));
            }
        }
    }
    let argv = split_command(&command);
    let resolved = match workdir {
        Some(dir) if dir.is_absolute() && dir.is_dir() => Some(dir),
        Some(dir) if dir.is_dir() => Some(dir),
        _ => find_backend_dir(),
    };
    (argv, resolved)
}

fn spawn_child(argv: &[String], workdir: Option<&Path>) -> std::io::Result<Child> {
    let mut command = Command::new(&argv[0]);
    command
        .args(&argv[1..])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(dir) = workdir {
        command.current_dir(dir);
    }
    command.spawn()
}

fn signal_terminate(pid: u32) {
    #[cfg(unix)]
    unsafe {
        libc::kill(pid as i32, libc::SIGTERM);
    }
    #[cfg(not(unix))]
    {
        let _ = Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T"])
            .spawn();
    }
}

fn token_from_line(line: &str) -> Option<String> {
    let index = line.find(TOKEN_MARKER)?;
    let token = line[index + TOKEN_MARKER.len()..].trim();
    if token.is_empty() {
        None
    } else {
        Some(token.to_string())
    }
}

/// Read a piped stream looking for the token log line; keeps draining the
/// pipe until EOF so the child never blocks on a full buffer.
fn scan_token<R: BufRead>(reader: R, tx: Sender<String>) {
    let mut sent = false;
    for line in reader.lines() {
        let Ok(line) = line else { break };
        if !sent {
            if let Some(token) = token_from_line(&line) {
                sent = true;
                let _ = tx.send(token);
            }
        }
    }
}

fn wait_for_token(rx: &Receiver<String>, state: &SidecarState) -> Option<String> {
    loop {
        match rx.recv_timeout(Duration::from_millis(250)) {
            Ok(token) => return Some(token),
            Err(RecvTimeoutError::Timeout) => {
                if state.stopping.load(Ordering::SeqCst) {
                    return None;
                }
            }
            Err(RecvTimeoutError::Disconnected) => return None,
        }
    }
}

fn bump_restart(state: &SidecarState) -> bool {
    let mut restarts = state.restarts.lock().unwrap();
    if *restarts >= MAX_SIDECAR_RESTARTS {
        return false;
    }
    *restarts += 1;
    true
}

fn set_lifecycle(app: &AppHandle, state: &SidecarState, lifecycle: SidecarLifecycle) {
    *state.lifecycle.lock().unwrap() = lifecycle;
    let _ = app.emit("sidecar-status", lifecycle.as_str());
}

/// Supervisor loop: spawn, harvest the token, reap, restart on crash
/// (up to MAX_SIDECAR_RESTARTS), exit on stop or clean exit.
fn run_supervisor(app: AppHandle, state: Arc<SidecarState>) {
    loop {
        if state.stopping.load(Ordering::SeqCst) {
            break;
        }
        set_lifecycle(&app, &state, SidecarLifecycle::Restarting);
        std::thread::sleep(Duration::from_millis(500));

        let (argv, workdir) = sidecar_config(&app);
        let mut child = match spawn_child(&argv, workdir.as_deref()) {
            Ok(child) => child,
            Err(err) => {
                eprintln!("[symbiot] sidecar spawn failed: {err}");
                if !bump_restart(&state) {
                    break;
                }
                continue;
            }
        };
        let pid = child.id();
        *state.child_pid.lock().unwrap() = Some(pid);
        if state.stopping.load(Ordering::SeqCst) {
            signal_terminate(pid);
        }
        set_lifecycle(&app, &state, SidecarLifecycle::Running);

        let (tx, rx) = mpsc::channel::<String>();
        if let Some(stdout) = child.stdout.take() {
            let tx = tx.clone();
            std::thread::spawn(move || scan_token(BufReader::new(stdout), tx));
        }
        if let Some(stderr) = child.stderr.take() {
            std::thread::spawn(move || scan_token(BufReader::new(stderr), tx));
        }
        if let Some(token) = wait_for_token(&rx, &state) {
            *state.token.lock().unwrap() = Some(token.clone());
            let _ = app.emit("sidecar-token", token);
        }

        let stop_started = Instant::now();
        let mut kill_sent = false;
        let exit_code = loop {
            match child.try_wait() {
                Ok(Some(status)) => break status.code(),
                Ok(None) => {}
                Err(_) => break None,
            }
            if state.stopping.load(Ordering::SeqCst)
                && !kill_sent
                && stop_started.elapsed() > Duration::from_secs(5)
            {
                let _ = child.kill();
                kill_sent = true;
            }
            std::thread::sleep(Duration::from_millis(250));
        };
        *state.child_pid.lock().unwrap() = None;

        if state.stopping.load(Ordering::SeqCst) {
            break;
        }
        match exit_code {
            Some(0) => break,
            _ => {
                if !bump_restart(&state) {
                    break;
                }
            }
        }
    }
    set_lifecycle(&app, &state, SidecarLifecycle::Stopped);
    state.supervisor.store(false, Ordering::SeqCst);
    state.stopping.store(false, Ordering::SeqCst);
}

// ---------------------------------------------------------------------------
// Sidecar commands
// ---------------------------------------------------------------------------

#[tauri::command]
fn launch_sidecar(app: AppHandle, state: State<'_, Arc<SidecarState>>) -> Result<String, String> {
    if state.supervisor.swap(true, Ordering::SeqCst) {
        if let Some(token) = state.token.lock().unwrap().clone() {
            let _ = app.emit("sidecar-token", token);
        }
        return Ok(state.lifecycle.lock().unwrap().as_str().to_string());
    }
    state.stopping.store(false, Ordering::SeqCst);
    *state.restarts.lock().unwrap() = 0;
    *state.child_pid.lock().unwrap() = None;
    let shared = Arc::clone(&state);
    std::thread::spawn(move || run_supervisor(app, shared));
    Ok("restarting".to_string())
}

#[tauri::command]
fn stop_sidecar(state: State<'_, Arc<SidecarState>>) -> Result<(), String> {
    state.stopping.store(true, Ordering::SeqCst);
    if let Some(pid) = *state.child_pid.lock().unwrap() {
        signal_terminate(pid);
    }
    Ok(())
}

#[tauri::command]
fn sidecar_status(state: State<'_, Arc<SidecarState>>) -> String {
    state.lifecycle.lock().unwrap().as_str().to_string()
}

// ---------------------------------------------------------------------------
// Sandbox proxy commands (sidecar API only — no direct Docker access)
// ---------------------------------------------------------------------------


// ---------------------------------------------------------------------------
// Provider keys (OS credential vault)
// ---------------------------------------------------------------------------

fn mask_secret(value: &str) -> String {
    if value.len() <= 8 {
        return "[redacted]".to_string();
    }
    let prefix: String = value.chars().take(3).collect();
    let suffix: String = value.chars().rev().take(4).collect::<String>().chars().rev().collect();
    format!("{}...{}", prefix, suffix)
}

fn validate_provider_key(provider: &str, value: &str) -> Result<(), String> {
    if value.trim() != value || value.len() < 8 || value.chars().any(char::is_whitespace) {
        return Err("API key must be non-empty and contain no whitespace".to_string());
    }
    let valid = match provider {
        "anthropic" => value.starts_with("sk-ant-"),
        "openrouter" => value.starts_with("sk-or-"),
        "openai" | "opencode" | "opencode_ai" => value.starts_with("sk-"),
        _ => true,
    };
    if !valid {
        return Err(format!("API key format is invalid for provider '{}'", provider));
    }
    Ok(())
}

#[derive(Serialize)]
struct SecretStatus {
    provider: String,
    configured: bool,
    masked: Option<String>,
}

#[tauri::command]
fn set_provider_key(provider: String, api_key: String) -> Result<SecretStatus, String> {
    validate_provider_key(&provider, &api_key)?;
    let entry = keyring::Entry::new("io.symbiot.mission-control", &provider)
        .map_err(|_| "OS credential vault is unavailable".to_string())?;
    entry
        .set_password(&api_key)
        .map_err(|_| "OS credential vault rejected the provider key".to_string())?;
    Ok(SecretStatus {
        provider,
        configured: true,
        masked: Some(mask_secret(&api_key)),
    })
}

#[tauri::command]
fn provider_key_status(provider: String) -> Result<SecretStatus, String> {
    let entry = keyring::Entry::new("io.symbiot.mission-control", &provider)
        .map_err(|_| "OS credential vault is unavailable".to_string())?;
    match entry.get_password() {
        Ok(value) => Ok(SecretStatus {
            provider,
            configured: true,
            masked: Some(mask_secret(&value)),
        }),
        Err(_) => Ok(SecretStatus {
            provider,
            configured: false,
            masked: None,
        }),
    }
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(Arc::new(SidecarState::new()))
        .invoke_handler(tauri::generate_handler![
            launch_sidecar,
            stop_sidecar,
            sidecar_status,
            set_provider_key,
            provider_key_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running symbiot desktop");
}

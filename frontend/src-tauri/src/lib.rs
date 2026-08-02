#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use serde::Serialize;
use std::process::Command;

const SANDBOX_CONTAINER: &str = "symbiot-desktop-sandbox";
const SANDBOX_IMAGE: &str = "symbiot-sandbox:latest";

#[derive(Serialize)]
struct DockerStatus {
    available: bool,
    version: Option<String>,
    message: String,
}

#[derive(Serialize)]
struct SandboxStatus {
    available: bool,
    running: bool,
    mode: String,
    message: String,
}

#[derive(Serialize)]
struct SecretStatus {
    provider: String,
    configured: bool,
    masked: Option<String>,
}

fn docker(args: &[&str]) -> Result<String, String> {
    let output = Command::new("docker")
        .args(args)
        .output()
        .map_err(|_| "Docker CLI was not found".to_string())?;
    if !output.status.success() {
        return Err("Docker daemon command failed".to_string());
    }
    Ok(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

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

#[tauri::command]
fn detect_docker() -> DockerStatus {
    match docker(&["version", "--format", "{{.Server.Version}}"]) {
        Ok(version) => DockerStatus {
            available: true,
            version: Some(version),
            message: "Docker daemon ready".to_string(),
        },
        Err(message) => DockerStatus {
            available: false,
            version: None,
            message,
        },
    }
}

#[tauri::command]
fn ensure_sandbox() -> Result<SandboxStatus, String> {
    docker(&["image", "inspect", SANDBOX_IMAGE])
        .map_err(|_| "Sandbox image is missing. Build backend/sandbox first.".to_string())?;
    let running = docker(&["inspect", "--format", "{{.State.Running}}", SANDBOX_CONTAINER])
        .map(|value| value == "true")
        .unwrap_or(false);
    if running {
        return Ok(SandboxStatus {
            available: true,
            running: true,
            mode: "local-docker".to_string(),
            message: "Existing sandbox is running".to_string(),
        });
    }
    let _ = docker(&["rm", "-f", SANDBOX_CONTAINER]);
    docker(&[
        "run",
        "-d",
        "--name",
        SANDBOX_CONTAINER,
        SANDBOX_IMAGE,
        "sleep",
        "infinity",
    ])?;
    Ok(SandboxStatus {
        available: true,
        running: true,
        mode: "local-docker".to_string(),
        message: "Sandbox started".to_string(),
    })
}

#[tauri::command]
fn stop_sandbox() -> Result<(), String> {
    let _ = docker(&["rm", "-f", SANDBOX_CONTAINER]);
    Ok(())
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

#[tauri::command]
fn configure_remote_sandbox(endpoint: String) -> Result<SandboxStatus, String> {
    let valid = (endpoint.starts_with("https://") || endpoint.starts_with("http://"))
        && !endpoint.chars().any(char::is_whitespace);
    if !valid {
        return Err("Remote sandbox endpoint must be an http(s) URL".to_string());
    }
    Ok(SandboxStatus {
        available: true,
        running: false,
        mode: "remote".to_string(),
        message: "Remote sandbox configured".to_string(),
    })
}

#[tauri::command]
fn enable_unsafe_local_mode(acknowledge: bool) -> Result<(), String> {
    if !acknowledge || std::env::var("SYMBIOT_ALLOW_UNSAFE_LOCAL").ok().as_deref() != Some("1") {
        return Err("Unsafe local mode requires explicit acknowledgement and SYMBIOT_ALLOW_UNSAFE_LOCAL=1".to_string());
    }
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            detect_docker,
            ensure_sandbox,
            stop_sandbox,
            set_provider_key,
            provider_key_status,
            configure_remote_sandbox,
            enable_unsafe_local_mode
        ])
        .run(tauri::generate_context!())
        .expect("error while running symbiot desktop");
}

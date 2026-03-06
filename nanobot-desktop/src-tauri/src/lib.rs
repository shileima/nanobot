//! nanobot Desktop - Tauri app that runs nanobot gateway and embeds webchat.

use std::io::Write;
use std::process::{Child, Command, Stdio};
use tauri::Manager;
use std::sync::Mutex;
use std::time::Duration;

#[derive(serde::Serialize)]
struct InitResult {
    success: bool,
    message: String,
}

#[derive(serde::Serialize)]
struct UpdateResult {
    success: bool,
    message: String,
}

/// Get ~/.nanobot path
fn nanobot_home() -> std::path::PathBuf {
    dirs::home_dir().unwrap_or_default().join(".nanobot")
}

/// Get logs directory
fn logs_dir() -> std::path::PathBuf {
    nanobot_home().join("logs")
}

/// Log a message to ~/.nanobot/logs/client.log
fn log_message(kind: &str, msg: &str) {
    if let Err(e) = (|| {
        let log_dir = logs_dir();
        std::fs::create_dir_all(&log_dir).ok();
        let log_file = log_dir.join("client.log");
        let timestamp = chrono::Local::now().format("%Y-%m-%d %H:%M:%S");
        let line = format!("[{}] [{}] {}\n", timestamp, kind, msg);
        std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_file)?
            .write_all(line.as_bytes())
    })() {
        eprintln!("Failed to write log: {}", e);
    }
}

/// Scan the filesystem for the `nanobot` binary.
/// macOS GUI apps (.app) launched from Finder get a minimal PATH that won't
/// include pip/pipx/uv installs, virtualenvs, or Homebrew. We search explicitly.
fn find_nanobot_bin() -> Option<std::path::PathBuf> {
    let home = dirs::home_dir().unwrap_or_default();

    let mut candidates: Vec<std::path::PathBuf> = vec![
        home.join(".local/bin/nanobot"),
        std::path::PathBuf::from("/opt/homebrew/bin/nanobot"),
        std::path::PathBuf::from("/usr/local/bin/nanobot"),
        home.join("bin/nanobot"),
        home.join(".cargo/bin/nanobot"),
    ];

    for ver in &["3.13", "3.12", "3.11", "3.10"] {
        candidates.push(home.join(format!("Library/Python/{}/bin/nanobot", ver)));
    }

    // Scan common virtualenv / project locations under ~/ai/
    if let Ok(entries) = std::fs::read_dir(home.join("ai")) {
        for entry in entries.flatten() {
            let venv_bin = entry.path().join(".venv/bin/nanobot");
            if venv_bin.exists() {
                candidates.push(venv_bin);
            }
        }
    }

    // Also check PATH from the login shell (best-effort, may fail from Finder)
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/zsh".to_string());
    if let Ok(output) = Command::new(&shell)
        .args(["-l", "-i", "-c", "which nanobot 2>/dev/null || echo ''"])
        .env("HOME", &home)
        .stderr(Stdio::null())
        .output()
    {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !path.is_empty() && std::path::Path::new(&path).exists() {
            candidates.insert(0, std::path::PathBuf::from(path));
        }
    }

    for c in &candidates {
        if c.exists() {
            log_message("DEBUG", &format!("Found nanobot at: {}", c.display()));
            return Some(c.clone());
        }
    }

    log_message("ERROR", "nanobot binary not found in any known location");
    None
}

/// Build an extended PATH that includes the directory where nanobot lives,
/// plus other common tool directories.
fn extended_path(nanobot_bin: &std::path::Path) -> String {
    let home = dirs::home_dir().unwrap_or_default();
    let current = std::env::var("PATH").unwrap_or_default();

    let mut dirs: Vec<String> = Vec::new();

    if let Some(parent) = nanobot_bin.parent() {
        dirs.push(parent.to_string_lossy().to_string());
    }

    for d in &[
        home.join(".local/bin"),
        std::path::PathBuf::from("/opt/homebrew/bin"),
        std::path::PathBuf::from("/usr/local/bin"),
        home.join(".cargo/bin"),
    ] {
        if d.exists() {
            dirs.push(d.to_string_lossy().to_string());
        }
    }

    dirs.push(current);
    dirs.join(":")
}

/// Create a Command for nanobot with extended PATH set.
fn nanobot_command() -> Command {
    match find_nanobot_bin() {
        Some(bin) => {
            let path = extended_path(&bin);
            let mut cmd = Command::new(&bin);
            cmd.env("PATH", &path);
            cmd.env("HOME", dirs::home_dir().unwrap_or_default());
            log_message("DEBUG", &format!("Using nanobot at: {}", bin.display()));
            cmd
        }
        None => {
            let mut cmd = Command::new("nanobot");
            cmd.env("HOME", dirs::home_dir().unwrap_or_default());
            log_message("WARN", "Falling back to bare 'nanobot' command");
            cmd
        }
    }
}

#[tauri::command]
fn init_workspace() -> InitResult {
    log_message("INFO", "Initializing workspace");
    match nanobot_command()
        .args(["onboard"])
        .output()
    {
        Ok(o) if o.status.success() => {
            log_message("INFO", "Workspace initialized");
            InitResult {
                success: true,
                message: "Workspace initialized".into(),
            }
        }
        Ok(o) => {
            let err = String::from_utf8_lossy(&o.stderr);
            log_message("ERROR", &format!("Onboard failed: {}", err));
            InitResult {
                success: false,
                message: format!("Onboard failed: {}", err),
            }
        }
        Err(e) => {
            log_message("ERROR", &format!("nanobot not found: {}", e));
            InitResult {
                success: false,
                message: format!("nanobot not found. Install with: pip install nanobot-ai. Error: {}", e),
            }
        }
    }
}

#[tauri::command]
fn update_nanobot() -> UpdateResult {
    log_message("INFO", "Starting nanobot update");
    match nanobot_command()
        .args(["update"])
        .output()
    {
        Ok(o) if o.status.success() => {
            log_message("INFO", "nanobot updated successfully");
            let out = String::from_utf8_lossy(&o.stdout);
            UpdateResult {
                success: true,
                message: if out.is_empty() { "Updated successfully".into() } else { out.trim().into() },
            }
        }
        Ok(o) => {
            let err = String::from_utf8_lossy(&o.stderr);
            log_message("ERROR", &format!("Update failed: {}", err));
            UpdateResult {
                success: false,
                message: format!("Update failed: {}", err),
            }
        }
        Err(e) => {
            log_message("ERROR", &format!("Update failed: {}", e));
            UpdateResult {
                success: false,
                message: format!("Update failed: {}", e),
            }
        }
    }
}

#[tauri::command]
fn check_workspace_ready() -> InitResult {
    let home = nanobot_home();
    let config = home.join("config.json");
    let workspace = home.join("workspace");
    if config.exists() && workspace.exists() {
        InitResult {
            success: true,
            message: "Ready".into(),
        }
    } else {
        InitResult {
            success: false,
            message: "Workspace not initialized".into(),
        }
    }
}

// Wait for webchat port to be listening
fn wait_for_port(port: u16, max_wait_ms: u64) -> bool {
    let start = std::time::Instant::now();
    while start.elapsed().as_millis() < max_wait_ms as u128 {
        if std::net::TcpStream::connect(format!("127.0.0.1:{}", port)).is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(200));
    }
    false
}

struct NanobotProcess(Mutex<Option<Child>>);

#[tauri::command]
fn get_nanobot_status(process: tauri::State<NanobotProcess>) -> std::result::Result<bool, String> {
    let mut guard = process.0.lock().map_err(|e| e.to_string())?;
    Ok(guard.as_mut().map(|c| c.try_wait().ok().flatten().is_none()).unwrap_or(false))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    log_message("INFO", "nanobot Desktop starting");

    let nanobot_home = nanobot_home();
    if !nanobot_home.join("config.json").exists() {
        std::fs::create_dir_all(&nanobot_home).ok();
        log_message("INFO", "First run: initializing workspace");
        let _ = init_workspace();
    }

    std::fs::create_dir_all(logs_dir()).ok();
    let gateway_log = logs_dir().join("gateway.log");
    let (stdout_io, stderr_io) = match std::fs::File::create(&gateway_log) {
        Ok(f) => {
            if let Ok(f2) = f.try_clone() {
                (Stdio::from(f), Stdio::from(f2))
            } else {
                (Stdio::from(f), Stdio::null())
            }
        }
        Err(_) => {
            log_message("WARN", "Could not create gateway.log");
            (Stdio::null(), Stdio::null())
        }
    };

    let child = nanobot_command()
        .args(["gateway", "--no-open-browser"])
        .stdout(stdout_io)
        .stderr(stderr_io)
        .spawn();

    let child = match child {
        Ok(c) => c,
        Err(e) => {
            log_message("ERROR", &format!("Failed to start nanobot: {}", e));
            eprintln!("Failed to start nanobot gateway: {}. Make sure nanobot is installed: pip install nanobot-ai", e);
            std::process::exit(1);
        }
    };

    log_message("INFO", "nanobot gateway process started");

    if !wait_for_port(17798, 15000) {
        log_message("WARN", "Webchat did not become ready in time");
    }

    let process_state = NanobotProcess(Mutex::new(Some(child)));

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(process_state)
        .invoke_handler(tauri::generate_handler![
            init_workspace,
            update_nanobot,
            check_workspace_ready,
            get_nanobot_status,
        ])
        .on_window_event(|_window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                log_message("INFO", "Window closed, shutting down nanobot");
            }
        })
        .build(tauri::generate_context!())
        .expect("error building tauri application")
        .run(move |app_handle, event| {
            if let tauri::RunEvent::Exit = event {
                log_message("INFO", "App exiting, terminating nanobot");
                if let Some(state) = app_handle.try_state::<NanobotProcess>() {
                    if let Ok(mut guard) = state.0.lock() {
                        if let Some(mut child) = guard.take() {
                            let _ = child.kill();
                            log_message("INFO", "nanobot process terminated");
                        }
                    }
                }
            }
        });
}

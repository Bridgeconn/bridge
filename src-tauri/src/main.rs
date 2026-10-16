// Prevents an additional console window on Windows in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;
mod sidecar;

use sidecar::EngineSidecar;
use tauri::{AppHandle, Manager, WindowEvent};

/// The longest the splash may stand alone (#287). The frontend reveals the
/// main window as soon as startup succeeds or fails, and declares a failure
/// itself after 30 s (STARTUP_TIMEOUT_MS), so this only fires if the main
/// window's page never got that far.
const SPLASH_FALLBACK: std::time::Duration = std::time::Duration::from_secs(45);

static REVEALED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// Show the main window and close the splash (#287), once. Later calls (the
/// splash's own close event, the fallback timer, a Retry after a failure) do
/// nothing, so a reviewer who has moved to another app is never pulled back.
pub(crate) fn reveal_main(app: &AppHandle) {
    if REVEALED.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    if let Some(main) = app.get_webview_window("main") {
        let _ = main.show();
        let _ = main.set_focus();
    }
    if let Some(splash) = app.get_webview_window("splash") {
        let _ = splash.close();
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(EngineSidecar::new())
        .setup(|app| {
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                let sidecar = handle.state::<EngineSidecar>();
                // start() has already recorded the failure as the "failed"
                // startup stage and in the diagnostics log (#233); this is
                // only the dev-terminal echo.
                if let Err(e) = sidecar.start(&handle).await {
                    eprintln!("Failed to start GreekRoomEngine sidecar: {e}");
                }
            });
            let fallback = app.handle().clone();
            std::thread::spawn(move || {
                std::thread::sleep(SPLASH_FALLBACK);
                reveal_main(&fallback);
            });
            Ok(())
        })
        // A splash closed by any route (Alt+F4 included) must not leave the
        // app running with no visible window: the main window shows instead.
        .on_window_event(|window, event| {
            if window.label() == "splash" && matches!(event, WindowEvent::Destroyed) {
                reveal_main(window.app_handle());
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::engine_call,
            commands::engine_log_recent,
            commands::frontend_log,
            commands::engine_startup_state,
            commands::reveal_main_window,
            commands::pick_project_folder,
            commands::pick_import_file,
            commands::pick_json_file,
            commands::pick_save_path,
        ])
        .build(tauri::generate_context!())
        .expect("error while running translationCore AI Bridge")
        // The sidecar is built to outlive any single request and nothing used
        // to stop it, so every closed window (and every Ctrl+C'd `tauri dev`)
        // left a bridge-engine.exe running. Besides the stray process, it kept
        // an open handle on the executable, which made the *next* build fail
        // inside tauri-build with a bare "Access is denied" as it tried to
        // refresh target/'s copy of that binary.
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit) {
                app.state::<EngineSidecar>().shutdown(app);
            }
        });
}

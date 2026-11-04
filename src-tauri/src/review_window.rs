//! #450: one auxiliary view over the existing engine, never another session.
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_window_state::{AppHandleExt, StateFlags, WindowExt};

pub const LABEL: &str = "review-queue";

#[tauri::command]
pub async fn review_window(app: AppHandle, window: WebviewWindow, action: String) -> Result<(), String> {
    if window.label() != "main" && window.label() != LABEL {
        return Err("Unsupported review window caller".into());
    }
    match action.as_str() {
        "open" => {
            // Created hidden at startup: Windows/WebView2 window creation
            // during a live command can stall the message loop. Opening only
            // reveals this existing view; it never constructs a second engine.
            let view = app.get_webview_window(LABEL)
                .ok_or("Review window is unavailable. Restart Bridge or use the main panel.")?;
            view.unminimize().map_err(|e| e.to_string())?;
            // Check again on every reopen, including after a monitor was
            // unplugged while this window was hidden. Never restore hidden.
            view.restore_state(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)
                .map_err(|e| e.to_string())?;
            view.show().map_err(|e| e.to_string())?;
            view.set_focus().map_err(|e| e.to_string())
        }
        "hide" => {
            if let Some(view) = app.get_webview_window(LABEL) {
                app.save_window_state(StateFlags::all()).map_err(|e| e.to_string())?;
                view.hide().map_err(|e| e.to_string())?;
            }
            Ok(())
        }
        _ => Err("Unsupported review window action".into()),
    }
}

pub fn close_with_main(app: &AppHandle) {
    if let Some(view) = app.get_webview_window(LABEL) {
        let _ = app.save_window_state(StateFlags::all());
        let _ = view.destroy();
    }
}

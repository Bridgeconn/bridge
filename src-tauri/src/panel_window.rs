//! Editor panels share the existing sidecar. No additional engine is started.
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_window_state::{AppHandleExt, StateFlags};

pub const PANELS: [&str; 4] = ["source", "reference", "paratext", "review"];
fn label(panel: &str) -> Result<String, String> {
    if !PANELS.contains(&panel) { return Err("Unsupported editor panel".into()); }
    Ok(format!("panel-{panel}"))
}
#[tauri::command]
pub async fn panel_window(app: AppHandle, window: WebviewWindow, panel: String, action: String) -> Result<(), String> {
    let target = label(&panel)?;
    if window.label() != "main" && window.label() != target { return Err("Unsupported panel window caller".into()); }
    let view = app.get_webview_window(&target).ok_or("Panel window is unavailable; restart Bridge or dock the panel")?;
    match action.as_str() {
        // On the main thread: see window_state.rs for why a command must not
        // restore or save window state itself.
        "open" => crate::window_state::reveal(&app, view).await,
        "hide" => crate::window_state::save_and_hide(&app, view).await,
        _ => Err("Unsupported panel window action".into()),
    }
}
pub fn close_with_main(app: &AppHandle) {
    let _ = app.save_window_state(StateFlags::all());
    for panel in PANELS { if let Some(view) = app.get_webview_window(&format!("panel-{panel}")) { let _ = view.destroy(); } }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn panel_labels_are_a_closed_inventory() {
        for panel in PANELS { assert_eq!(label(panel).unwrap(), format!("panel-{panel}")); }
        for invalid in ["main", "alignment", "review-queue", "../source", "languageQa", ""] { assert!(label(invalid).is_err()); }
    }
}

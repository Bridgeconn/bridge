//! Editor panels share the existing sidecar. No additional engine is started.
use tauri::{AppHandle, Manager, WebviewWindow};
use tauri_plugin_window_state::{AppHandleExt, StateFlags};

/// Every panel that can stand in a window of its own. `reference2` to
/// `reference4` are the reference tabs a reviewer adds beside the project's
/// own (#519). A window cannot be made while the app runs (see
/// alignment_window.rs), so each one is declared, hidden, in tauri.conf.json,
/// and this list, that file and the frontend's `SIDE_PANEL_ORDER` name the
/// same panels.
pub const PANELS: [&str; 7] = ["source", "reference", "reference2", "reference3", "reference4", "paratext", "review"];
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
        // Already showing: to the front, where the user left it (#519).
        "focus" => crate::window_state::focus(&app, view).await,
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
        for invalid in ["main", "alignment", "review-queue", "../source", "languageQa", "reference1", "reference5", "reference-2", ""] { assert!(label(invalid).is_err()); }
    }
    /// A panel with no declared window cannot be shown separately, and a
    /// declared window that is not a panel is never hidden or closed with the
    /// rest: the two lists must name the same windows.
    #[test] fn every_panel_has_a_declared_window_and_the_other_way_round() {
        let config: serde_json::Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        let mut declared: Vec<String> = config["app"]["windows"].as_array().unwrap().iter()
            .filter_map(|window| window["label"].as_str())
            .filter(|label| label.starts_with("panel-")).map(str::to_string).collect();
        let mut expected: Vec<String> = PANELS.iter().map(|panel| format!("panel-{panel}")).collect();
        declared.sort(); expected.sort();
        assert_eq!(declared, expected);
        let main = include_str!("main.rs");
        for label in &expected { assert!(main.contains(&format!("skip_initial_state(\"{label}\")")), "{label} is not skipped at startup"); }
    }
}

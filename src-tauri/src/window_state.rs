//! Saving and restoring window state from a command, on the main thread.
//!
//! `tauri-plugin-window-state` holds its cache lock for the whole of
//! `save_window_state` and `restore_state`, and inside that reads or sets the
//! window (size, position, maximized, visible). Called from a command, which
//! runs on a worker thread, each of those is sent to the main thread and
//! waited for. The plugin's own move/resize handler runs on the main thread
//! and takes the same lock. So a save on a worker while the main thread
//! handles a move or resize stops both for good: the worker holds the lock
//! and waits for the main thread, the main thread waits for the lock.
//!
//! That is what froze 0.25.0 on its splash (2026-11-12): the main page asks
//! for the review-queue window to be hidden as it mounts, and in a release
//! build that arrived while the startup windows were still being created and
//! sized. A debug build loads its pages later and did not show it.
//!
//! On the main thread the window calls are direct and the handler cannot run
//! in between, so everything here goes through `on_main`. Window commands
//! must use `reveal` and `save_and_hide`, never the plugin's calls directly.
use tauri::{AppHandle, WebviewWindow};
use tauri_plugin_window_state::{AppHandleExt, StateFlags, WindowExt};

/// Run `work` on the main thread and hand back what it returned.
pub(crate) async fn on_main<T: Send + 'static>(
    app: &AppHandle,
    work: impl FnOnce() -> T + Send + 'static,
) -> Result<T, String> {
    let (tx, rx) = tokio::sync::oneshot::channel();
    app.run_on_main_thread(move || {
        let _ = tx.send(work());
    })
    .map_err(|e| e.to_string())?;
    rx.await.map_err(|e| e.to_string())
}

/// Show a window that was created hidden: back from minimized, at its saved
/// size and place (checked again on every open, so a window whose monitor was
/// unplugged while it was hidden lands on screen), then shown and focused.
pub(crate) async fn reveal(app: &AppHandle, view: WebviewWindow) -> Result<(), String> {
    on_main(app, move || -> tauri::Result<()> {
        view.unminimize()?;
        // Never restore VISIBLE: a window saved hidden would stay hidden.
        view.restore_state(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)?;
        view.show()?;
        view.set_focus()
    })
    .await?
    .map_err(|e| e.to_string())
}

/// Save every window's state, then hide this one.
pub(crate) async fn save_and_hide(app: &AppHandle, view: WebviewWindow) -> Result<(), String> {
    let handle = app.clone();
    on_main(app, move || -> Result<(), String> {
        handle.save_window_state(StateFlags::all()).map_err(|e| e.to_string())?;
        view.hide().map_err(|e| e.to_string())
    })
    .await?
}

#[cfg(test)]
mod tests {
    /// The window commands run on worker threads: none of them may call the
    /// plugin's save or restore itself. `close_with_main` may; it is called
    /// from the main thread's window-event handler.
    #[test]
    fn window_commands_save_and_restore_only_through_this_module() {
        for (name, source) in [
            ("review_window.rs", include_str!("review_window.rs")),
            ("alignment_window.rs", include_str!("alignment_window.rs")),
            ("panel_window.rs", include_str!("panel_window.rs")),
        ] {
            let commands = source.split("pub fn close_with_main").next().unwrap();
            assert!(!commands.contains("save_window_state("), "{name} saves window state off the main thread");
            assert!(!commands.contains("restore_state("), "{name} restores window state off the main thread");
            assert!(commands.contains("window_state::reveal(") && commands.contains("window_state::save_and_hide("), "{name}");
        }
    }
}

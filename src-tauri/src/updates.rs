//! Optional signed GitHub updates (#321). No update ever installs during work:
//! a verified download is held until the user exits the application normally.
use std::sync::Mutex;
use std::time::Duration;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_updater::{Update, UpdaterExt};

#[derive(Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateStatus {
    pub phase: String,
    pub version: Option<String>,
    pub notes: Option<String>,
    pub message: String,
}

impl Default for UpdateStatus {
    fn default() -> Self {
        Self {
            phase: "idle".into(),
            version: None,
            notes: None,
            message: String::new(),
        }
    }
}

struct Session {
    automatic: bool,
    generation: u64,
    status: UpdateStatus,
    staged: Option<(Update, Vec<u8>)>,
    installing: bool,
}

impl Default for Session {
    fn default() -> Self {
        Self {
            automatic: true,
            generation: 0,
            status: UpdateStatus::default(),
            staged: None,
            installing: false,
        }
    }
}

#[derive(Default)]
pub struct AppUpdates {
    session: Mutex<Session>,
    check_lock: tokio::sync::Mutex<()>,
}

fn publish(app: &AppHandle, session: &Session) {
    let _ = app.emit("bridge-update", &session.status);
}

#[tauri::command]
pub fn update_status(state: State<'_, AppUpdates>) -> UpdateStatus {
    state.session.lock().unwrap().status.clone()
}

#[tauri::command]
pub fn configure_updates(app: AppHandle, state: State<'_, AppUpdates>, enabled: bool) {
    let mut session = state.session.lock().unwrap();
    if session.automatic != enabled {
        session.automatic = enabled;
        // Invalidate an in-flight automatic check/download before discarding it.
        session.generation += 1;
        session.staged = None;
        session.status = UpdateStatus::default();
        publish(&app, &session);
    }
}

fn can_finish(session: &Session, generation: u64, automatic: bool) -> bool {
    session.generation == generation && (!automatic || session.automatic)
}

#[tauri::command]
pub async fn check_updates(
    app: AppHandle,
    state: State<'_, AppUpdates>,
    download: bool,
    automatic: bool,
) -> Result<(), String> {
    // Drop duplicate requests rather than queuing several large downloads.
    let Ok(_guard) = state.check_lock.try_lock() else {
        return Ok(());
    };
    let generation = {
        let mut session = state.session.lock().unwrap();
        if (automatic && !session.automatic) || session.staged.is_some() {
            return Ok(());
        }
        session.status = UpdateStatus {
            phase: "checking".into(),
            ..Default::default()
        };
        publish(&app, &session);
        session.generation
    };
    let public_key = option_env!("BRIDGE_UPDATER_PUBLIC_KEY")
        .unwrap_or("")
        .trim();
    let unavailable = if !cfg!(windows) {
        Some("In-app updates are currently supported on Windows. Install other platforms from GitHub Releases.")
    } else if cfg!(debug_assertions) {
        Some("Update checks are disabled in development builds.")
    } else if public_key.is_empty() {
        Some("This build has no updater signing key. Install a signed release to receive updates.")
    } else {
        None
    };
    if let Some(message) = unavailable {
        let mut session = state.session.lock().unwrap();
        session.status.phase = "unavailable".into();
        session.status.message = message.into();
        publish(&app, &session);
        return Ok(());
    }
    let result = async {
        let exit_app = app.clone();
        let updater = app
            .updater_builder()
            .pubkey(public_key)
            // The download can include both frozen sidecars and bundled resources.
            .timeout(Duration::from_secs(30 * 60))
            .on_before_exit(move || {
                exit_app
                    .state::<crate::sidecar::EngineSidecar>()
                    .shutdown(&exit_app);
                exit_app.cleanup_before_exit();
            })
            .build()
            .map_err(|e| e.to_string())?;
        let update = tokio::time::timeout(Duration::from_secs(20), updater.check())
            .await
            .map_err(|_| "The update check timed out.".to_string())?
            .map_err(|e| e.to_string())?;
        {
            let mut session = state.session.lock().unwrap();
            if !can_finish(&session, generation, automatic) {
                return Ok(());
            }
            let Some(ref update) = update else {
                session.status.phase = "current".into();
                session.status.message = "Bridge is up to date.".into();
                publish(&app, &session);
                return Ok(());
            };
            session.status.version = Some(update.version.clone());
            session.status.notes = update.body.clone();
            session.status.phase = if download { "downloading" } else { "available" }.into();
            session.status.message = if download {
                "Downloading a signed update…"
            } else {
                "An update is available."
            }
            .into();
            publish(&app, &session);
        }
        if download {
            let update = update.unwrap();
            // download() verifies the mandatory signature before returning bytes.
            let bytes = update
                .download(|_, _| {}, || {})
                .await
                .map_err(|e| e.to_string())?;
            let mut session = state.session.lock().unwrap();
            if can_finish(&session, generation, automatic) {
                session.staged = Some((update, bytes));
                session.status.phase = "ready".into();
                session.status.message =
                    "Update downloaded. It will install when you close Bridge.".into();
                publish(&app, &session);
            }
        }
        Ok::<(), String>(())
    }
    .await;
    if let Err(ref error) = result {
        let mut session = state.session.lock().unwrap();
        if can_finish(&session, generation, automatic) {
            session.status.phase = "error".into();
            session.status.message = format!(
                "Could not update Bridge. You can keep working and try again later. {error}"
            );
            publish(&app, &session);
        }
    }
    result
}

/// Called only on ExitRequested, never because a download finished. Prevent the
/// event while the worker extracts/launches the installer. Windows install()
/// exits directly; its before-exit hook must shut down the sidecar explicitly.
pub fn install_on_exit(app: &AppHandle, api: &tauri::ExitRequestApi) {
    let state = app.state::<AppUpdates>();
    let mut session = state.session.lock().unwrap();
    if session.installing {
        api.prevent_exit();
        return;
    }
    let staged = session.staged.take();
    let Some((update, bytes)) = staged else {
        return;
    };
    session.installing = true;
    drop(session);
    api.prevent_exit();
    let app = app.clone();
    std::thread::spawn(move || {
        if let Err(error) = update.install(bytes) {
            tauri::async_runtime::block_on(
                app.state::<crate::sidecar::EngineSidecar>()
                    .log_from_frontend("error", format!("Update installation failed: {error}")),
            );
        }
        app.state::<AppUpdates>().session.lock().unwrap().installing = false;
        app.exit(0);
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn automatic_updates_default_on_but_never_start_with_an_installer() {
        let session = Session::default();
        assert!(session.automatic);
        assert!(session.staged.is_none());
    }

    #[test]
    fn disabling_during_download_prevents_staging_even_after_reenabling() {
        let mut session = Session::default();
        let started = session.generation;
        session.automatic = false;
        session.generation += 1;
        assert!(!can_finish(&session, started, true));
        session.automatic = true;
        session.generation += 1;
        assert!(!can_finish(&session, started, true));
        assert!(can_finish(&session, session.generation, true));
    }

    #[test]
    fn manual_check_works_with_automatic_updates_disabled() {
        let mut session = Session::default();
        session.automatic = false;
        assert!(can_finish(&session, 0, false));
        assert!(!can_finish(&session, 0, true));
    }
}

; Bridge installer hooks (tauri.conf.json bundle.windows.nsis.installerHooks).
;
; #282: after Bridge is installed, offer to install Bridge's Paratext connector.
; The engine does the work (engine/tc_ai_bridge/paratext_install.py): it finds
; Paratext 9, compiles the connector against that installation, and copies it
; into Paratext's plugins folder through one Windows administrator prompt. Bridge
; itself installs per user and never needs administrator rights.
;
; Skipped on a silent install and when Paratext 9 is not registered. The engine's
; exit codes: 0 installed, 1 failed, 2 Paratext is running, 3 the admin prompt was
; declined, 4 already current, 5 no Paratext 9. The same install is always
; available later in Bridge: Settings > Connections.

!macro NSIS_HOOK_POSTINSTALL
  IfSilent bridge_connector_done
  ; A 32-bit installer reads the WOW6432Node view, which is where Paratext 9 registers.
  ReadRegStr $1 HKLM "SOFTWARE\Paratext\8" "Paratext9_Full_Release_AppPath"
  StrCmp $1 "" bridge_connector_done
  MessageBox MB_YESNO|MB_ICONQUESTION "Paratext 9 is installed on this computer.$\r$\n$\r$\nInstall Bridge's Paratext connector now, so that Bridge and Paratext follow each other's verse?$\r$\n$\r$\nClose Paratext first. Windows will ask for administrator permission once.$\r$\nYou can also do this later in Bridge: Settings > Connections." IDNO bridge_connector_done
  bridge_connector_retry:
    nsExec::Exec '"$INSTDIR\bridge-engine.exe" --install-paratext-connector'
    Pop $0
    StrCmp $0 "0" 0 bridge_connector_not_installed
      MessageBox MB_OK|MB_ICONINFORMATION "The Paratext connector is installed.$\r$\n$\r$\nStart Paratext, then turn on Paratext navigation in Bridge: Settings > Connections."
      Goto bridge_connector_done
  bridge_connector_not_installed:
    StrCmp $0 "4" bridge_connector_done
    StrCmp $0 "2" 0 bridge_connector_failed
      MessageBox MB_RETRYCANCEL|MB_ICONEXCLAMATION "Paratext is open. Close Paratext, then click Retry." IDRETRY bridge_connector_retry
      Goto bridge_connector_done
  bridge_connector_failed:
    MessageBox MB_OK|MB_ICONEXCLAMATION "The Paratext connector was not installed.$\r$\n$\r$\nYou can install it later in Bridge: Settings > Connections."
  bridge_connector_done:
!macroend

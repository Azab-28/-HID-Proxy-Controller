!include MUI2.nsh

Name "HID Proxy Controller"
OutFile "HIDProxyController_1.7.0_Setup.exe"
InstallDir "$LOCALAPPDATA\HIDProxyController"
RequestExecutionLevel user
Unicode true

!define MUI_ABORTWARNING
!define MUI_ICON "${NSISDIR}\Contrib\Graphics\Icons\modern-install.ico"
!define MUI_UNICON "${NSISDIR}\Contrib\Graphics\Icons\modern-uninstall.ico"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_WELCOME
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_UNPAGE_FINISH

!insertmacro MUI_LANGUAGE "English"

Section "Main Application" SecMain
    SetOutPath "$INSTDIR"
    File /r "dist\__main__.dist\*.*"
    WriteUninstaller "$INSTDIR\uninstall.exe"

    WriteRegStr HKCU "Software\HIDProxy" "InstallDir" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\HIDProxyController" "DisplayName" "HID Proxy Controller"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\HIDProxyController" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\HIDProxyController" "DisplayVersion" "1.7.0"

    CreateDirectory "$SMPROGRAMS\HID Proxy Controller"
    CreateShortcut "$SMPROGRAMS\HID Proxy Controller\HID Proxy Controller.lnk" "$INSTDIR\HIDProxyController.exe"
    CreateShortcut "$SMPROGRAMS\HID Proxy Controller\Uninstall.lnk" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Desktop Shortcut" SecDesktop
    CreateShortcut "$DESKTOP\HID Proxy Controller.lnk" "$INSTDIR\HIDProxyController.exe"
SectionEnd

Section "Uninstall"
    Delete "$DESKTOP\HID Proxy Controller.lnk"
    RMDir /r "$SMPROGRAMS\HID Proxy Controller"
    RMDir /r "$INSTDIR"
    DeleteRegKey HKCU "Software\HIDProxy"
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\HIDProxyController"
    DeleteRegValue HKCU "Software\Microsoft\Windows\CurrentVersion\Run" "HIDProxyController"
SectionEnd

Function .onInit
    System::Call 'kernel32::CreateMutexW(i 0, i 1, t "Local\HIDProxyControllerLock") i .r0'
    System::Call 'kernel32::GetLastError() i .r1'
    ${If} $1 == 183
        MessageBox MB_OK|MB_ICONEXCLAMATION "Application is already running. Please close it first."
        Abort
    ${EndIf}
FunctionEnd

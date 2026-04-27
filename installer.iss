; Inno Setup script for PD-72 Application Record Builder
; Bundles: PD72Builder app, Tesseract OCR, Ghostscript

#define AppName "PD-72 Application Record Builder"
#define AppVersion "1.0"
#define AppPublisher "Fireside Law"
#define AppExeName "PD72Builder.exe"

[Setup]
AppId={{A1B2C3D4-1234-5678-ABCD-EF0123456789}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\PD72Builder
DefaultGroupName={#AppName}
OutputDir=dist\installer
OutputBaseFilename=PD72Builder-Setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Main application folder (PyInstaller output)
Source: "dist\PD72Builder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Bundled dependency installers (run silently during install)
Source: "installers\tesseract-setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "installers\ghostscript-setup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
; Install Tesseract silently (adds itself to PATH)
Filename: "{tmp}\tesseract-setup.exe"; Parameters: "/S"; StatusMsg: "Installing Tesseract OCR..."; Flags: waituntilterminated
; Install Ghostscript silently
Filename: "{tmp}\ghostscript-setup.exe"; Parameters: "/S"; StatusMsg: "Installing Ghostscript..."; Flags: waituntilterminated
; Launch the app after install (optional)
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Nothing extra — Tesseract and Ghostscript have their own uninstallers

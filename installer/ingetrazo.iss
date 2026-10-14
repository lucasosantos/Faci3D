; Inno Setup script for Faci3D (installer kept from IngeTrazo).
;
; Builds a professional Windows installer: multilingual wizard, GPL license page,
; shortcuts, "Add or Remove Programs" entry and a clean uninstaller.
;
; Local build (needs Inno Setup 6+):
;     iscc /DMyAppVersion=0.2.0 installer\ingetrazo.iss
;
; CI build: see .github/workflows/build-windows.yml
;
; The AppId is a FIXED GUID — never change it between versions, or Windows
; treats every release as a different app and upgrades stop being clean.

#define MyAppName "Faci3D"
#define MyAppPublisher "Lucas Oliveira"
#define MyAppURL "https://github.com/lucasosantos/Faci3D"
#define MyAppExeName "ingetrazo.exe"

; MyAppVersion is injected from the build command with /DMyAppVersion=X.Y.Z
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0-dev"
#endif

[Setup]
; FIXED AppId GUID — generated once for Faci3D (IngeTrazo's is another, so
; the two install side by side). Changing it breaks upgrades.
AppId={{7B58112B-CB6F-40E3-9398-C4381A124DD4}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription=Modelador 3D para impressao 3D
VersionInfoProductName={#MyAppName}

DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Free software: the "license" page shows the GPL-3.0 text.
LicenseFile=..\LICENSE

OutputDir=..\dist
OutputBaseFilename=faci3d-setup-v{#MyAppVersion}

WizardStyle=modern
; (Saved as UTF-8 WITH a BOM: that is how Inno Setup knows the texts
; below are UTF-8 — without it «Associações» would come out garbled.)
; The wizard speaks the language of Windows (English, Spanish, Brazilian
; Portuguese or Polish) and asks only when none of them matches (issue #135).
ShowLanguageDialog=auto
DisableProgramGroupPage=yes
; We register file-type icons/associations — tells Explorer to refresh them.
ChangesAssociations=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\resources\icons\ingetrazo.ico

[Languages]
; English first: it is the fallback when Windows speaks something else.
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "polish"; MessagesFile: "compiler:Languages\Polish.isl"

[CustomMessages]
english.SkpDefault=Open .skp files with Faci3D (double-click)
english.FileAssociations=File associations:
english.IgzDocument=Faci3D project
english.LegacyDocument=IngeTrazo document (Faci3D)
english.DaeModel=COLLADA model (Faci3D)
english.SkpModel=SKP model (Faci3D)
spanish.SkpDefault=Abrir archivos .skp con Faci3D (doble clic)
spanish.FileAssociations=Asociaciones de archivos:
spanish.IgzDocument=Proyecto de Faci3D
spanish.LegacyDocument=Documento de IngeTrazo (Faci3D)
spanish.DaeModel=Modelo COLLADA (Faci3D)
spanish.SkpModel=Modelo SKP (Faci3D)
brazilianportuguese.SkpDefault=Abrir arquivos .skp com o Faci3D (clique duplo)
brazilianportuguese.FileAssociations=Associações de arquivos:
brazilianportuguese.IgzDocument=Projeto do Faci3D
brazilianportuguese.LegacyDocument=Documento do IngeTrazo (Faci3D)
brazilianportuguese.DaeModel=Modelo COLLADA (Faci3D)
brazilianportuguese.SkpModel=Modelo SKP (Faci3D)
polish.SkpDefault=Otwieraj pliki .skp w Faci3D (dwukrotne kliknięcie)
polish.FileAssociations=Skojarzenia plików:
polish.IgzDocument=Projekt Faci3D
polish.LegacyDocument=Dokument IngeTrazo (Faci3D)
polish.DaeModel=Model COLLADA (Faci3D)
polish.SkpModel=Model SKP (Faci3D)

[Tasks]
Name: "skpdefault"; Description: "{cm:SkpDefault}"; \
    GroupDescription: "{cm:FileAssociations}"
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; The whole PyInstaller one-dir bundle.
Source: "..\dist\ingetrazo\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs
; Branded document icons, copied to the {app} root so [Registry] DefaultIcon
; entries can reference them with a stable path.
Source: "..\resources\icons\mimetypes\ingetrazo-igz.ico"; DestDir: "{app}"; \
    Flags: ignoreversion
Source: "..\resources\icons\mimetypes\ingetrazo-dae.ico"; DestDir: "{app}"; \
    Flags: ignoreversion
Source: "..\resources\icons\mimetypes\ingetrazo-skp.ico"; DestDir: "{app}"; \
    Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; \
    Tasks: desktopicon

[Registry]
; ── Hybrid laptops (Intel + NVIDIA/AMD): run on the discrete GPU ─────────────
; This is the value Settings ▸ System ▸ Display ▸ Graphics writes when the user
; picks "High performance" for a program; without it Windows starts Faci3D
; on the integrated chip and the viewport crawls. Only written when the user
; has not chosen anything yet (the app repeats the check at start-up).
Root: HKCU; Subkey: "Software\Microsoft\DirectX\UserGpuPreferences"; \
    ValueType: string; ValueName: "{app}\{#MyAppExeName}"; \
    ValueData: "GpuPreference=2;"; Flags: createvalueifdoesntexist uninsdeletevalue

; ── .faci3d — Faci3D's own format: full association + document icon ───────
; Double-click opens the project in Faci3D and Explorer shows its icon.
Root: HKA; Subkey: "Software\Classes\.faci3d"; ValueType: string; \
    ValueData: "Faci3D.Document"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Faci3D.Document"; ValueType: string; \
    ValueData: "{cm:IgzDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Faci3D.Document\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingetrazo-igz.ico,0"
Root: HKA; Subkey: "Software\Classes\Faci3D.Document\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""

; ── .igz — IngeTrazo's document: "Open with" only ───────────────────────────
; It opens as a new unsaved project; double-click stays with IngeTrazo when
; it is installed.
Root: HKA; Subkey: "Software\Classes\Faci3D.igz"; ValueType: string; \
    ValueData: "{cm:LegacyDocument}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Faci3D.igz\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingetrazo-igz.ico,0"
Root: HKA; Subkey: "Software\Classes\Faci3D.igz\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.igz\OpenWithProgids"; \
    ValueType: string; ValueName: "Faci3D.igz"; ValueData: ""; \
    Flags: uninsdeletevalue

; ── .dae / .skp — standard interchange formats: "Open with" only ────────────
; We DO NOT take over the default program or the file icon (Windows ties the
; shown icon to the default handler, and stealing .dae/.skp from the
; programs the user already has would surprise them). Instead we register a ProgId and add it to
; each extension's OpenWithProgids list, so Faci3D appears in the right-click
; "Open with" menu. The ProgId carries the branded icon, which only takes visual
; effect if the user later chooses Faci3D as the default for these files.
Root: HKA; Subkey: "Software\Classes\Faci3D.dae"; ValueType: string; \
    ValueData: "{cm:DaeModel}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Faci3D.dae\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingetrazo-dae.ico,0"
Root: HKA; Subkey: "Software\Classes\Faci3D.dae\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.dae\OpenWithProgids"; \
    ValueType: string; ValueName: "Faci3D.dae"; ValueData: ""; \
    Flags: uninsdeletevalue

Root: HKA; Subkey: "Software\Classes\Faci3D.skp"; ValueType: string; \
    ValueData: "{cm:SkpModel}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\Faci3D.skp\DefaultIcon"; \
    ValueType: string; ValueData: "{app}\ingetrazo-skp.ico,0"
Root: HKA; Subkey: "Software\Classes\Faci3D.skp\shell\open\command"; \
    ValueType: string; ValueData: """{app}\{#MyAppExeName}"" ""%1"""
Root: HKA; Subkey: "Software\Classes\.skp\OpenWithProgids"; \
    ValueType: string; ValueName: "Faci3D.skp"; ValueData: ""; \
    Flags: uninsdeletevalue
; Optional task: make Faci3D the DEFAULT opener for .skp (double-click).
; Checked by default — .skp now opens natively (openskp backend). Users who
; prefer another program for .skp can untick it; uninstall removes the value
; and Windows falls back to the previous handler.
Root: HKA; Subkey: "Software\Classes\.skp"; ValueType: string; \
    ValueData: "Faci3D.skp"; Tasks: skpdefault; Flags: uninsdeletevalue

[Run]
Filename: "{app}\{#MyAppExeName}"; \
    Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

#define AppName "Cruzador Excel - Banco Piano"
#define AppExeName "CruzadorExcel-Windows.exe"
#define AppSourceDir "build\windows\CruzadorExcel-Windows"

[Setup]
AppId={{58B05EF3-2A2F-43B6-9882-52D2CE040E1D}
AppName={#AppName}
AppVersion=Demo
AppPublisher=Banco Piano
DefaultDirName={localappdata}\Programs\Banco Piano\Cruzador Excel
DefaultGroupName={#AppName}
UninstallDisplayName={#AppName}
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\..\salidas\exes
OutputBaseFilename=CruzadorExcel-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: unchecked

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer_windows_leeme.txt"; DestDir: "{app}"; DestName: "LEEME.txt"; Flags: ignoreversion

[Dirs]
Name: "{localappdata}\BancoPiano\CruzadorExcel"; Flags: uninsneveruninstall

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{localappdata}\BancoPiano\CruzadorExcel"
Name: "{autodesktop}\Cruzador Excel"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{localappdata}\BancoPiano\CruzadorExcel"; Tasks: desktopicon
Name: "{autoprograms}\Instrucciones - Cruzador Excel"; Filename: "{sys}\notepad.exe"; Parameters: """{app}\LEEME.txt"""

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Abrir Cruzador Excel"; WorkingDir: "{localappdata}\BancoPiano\CruzadorExcel"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := MsgBox(
    'Esta es una version de demostracion que incluye el usuario dev / dev1234.' + #13#10 + #13#10 +
    'Usela exclusivamente con datos sinteticos. No cargue informacion real, personal ni de clientes.' + #13#10 + #13#10 +
    'Desea continuar con la instalacion?',
    mbConfirmation, MB_YESNO) = IDYES;
end;

; Inno Setup installer around the PyInstaller exe (build that first: pyinstaller aion2market.spec).
;   iscc /DAppVersion=0.1.0 installer\aion2market.iss     -> dist\Aion2Market-Setup-0.1.0.exe
; Installs per user (no admin). Npcap is not bundled: its free license doesn't allow redistribution,
; so the wizard explains what it adds and offers to open its download page.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Aion 2 Market"
#define AppExe "Aion2Market.exe"
#define NpcapUrl "https://npcap.com/#download"

[Setup]
AppId={{A47E6054-CB00-4E40-AFDE-48053D9F5870}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=aion2market
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=Aion2Market-Setup-{#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; the uninstaller may remove SSLKEYLOGFILE; tell running programs
ChangesEnvironment=yes

[Languages]
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
tr.NpcapTitle=Npcap ile canlı fiyatlar
tr.NpcapActiveSub=Npcap kurulu: canlı fiyat kaydı aktif olacak.
tr.NpcapActiveText=Oyunda pazarı açtığında ya da bir item aradığında gelen fiyatlar anında kaydedilir. Uygulamada sağ üstte "Npcap kurulumu aktif" yazısını göreceksin.
tr.NpcapMissingSub=Npcap kurarsan daha güncel fiyatlar alırsın.
tr.NpcapMissingText=Npcap kurulu değil. Uygulama onsuz da açılır, ama oyunda açtığın pazar aramalarını kaydedemez. Npcap kurarsan bu aramalar anında kaydedilir ve en güncel fiyatlar böyle gelir.%n%nNpcap ayrı bir ücretsiz programdır, bu kurulumla birlikte gelmez. Kurarken "WinPcap API-compatible Mode" seçili kalsın, sonra uygulamayı yeniden başlat. Daha sonra da kurabilirsin.
tr.NpcapOpenPage=Kurulumdan sonra Npcap indirme sayfasını aç
tr.DeleteData=Kayıtlı fiyatlar, ayarlar ve anahtar dosyası (AppData\Local\aion2market) da silinsin mi?
en.NpcapTitle=Live prices with Npcap
en.NpcapActiveSub=Npcap is installed: live price recording will be active.
en.NpcapActiveText=Prices are recorded as soon as you open the market or search an item in game. The app shows "Npcap installation active" at the top right.
en.NpcapMissingSub=Install Npcap to get more up-to-date prices.
en.NpcapMissingText=Npcap is not installed. The app opens without it, but it can't record the market searches you open in game. With Npcap those searches are recorded instantly, and that's how the freshest prices come in.%n%nNpcap is a separate free program and isn't included in this setup. Keep "WinPcap API-compatible Mode" selected while installing it, then restart the app. You can also install it later.
en.NpcapOpenPage=Open the Npcap download page after setup
en.DeleteData=Also delete recorded prices, settings and the key file (AppData\Local\aion2market)?

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[Code]
var
  NpcapPage: TInputOptionWizardPage;
  NpcapMissing: Boolean;

// Same check as the app (app.npcap_installed), plus the driver's service entry.
function NpcapInstalled: Boolean;
begin
  Result := DirExists(ExpandConstant('{sys}\Npcap')) or
            RegKeyExists(HKLM, 'SYSTEM\CurrentControlSet\Services\npcap');
end;

procedure InitializeWizard;
begin
  NpcapMissing := not NpcapInstalled;
  if NpcapMissing then
  begin
    NpcapPage := CreateInputOptionPage(wpSelectTasks, CustomMessage('NpcapTitle'),
      CustomMessage('NpcapMissingSub'), CustomMessage('NpcapMissingText'), False, False);
    NpcapPage.Add(CustomMessage('NpcapOpenPage'));
    NpcapPage.Values[0] := True;
  end
  else
    NpcapPage := CreateInputOptionPage(wpSelectTasks, CustomMessage('NpcapTitle'),
      CustomMessage('NpcapActiveSub'), CustomMessage('NpcapActiveText'), False, False);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ErrorCode: Integer;
begin
  if (CurStep = ssPostInstall) and NpcapMissing and NpcapPage.Values[0] and not WizardSilent then
    ShellExec('open', '{#NpcapUrl}', '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, Keylog: String;
begin
  if CurUninstallStep <> usPostUninstall then
    Exit;
  DataDir := ExpandConstant('{localappdata}\aion2market');
  // The app set SSLKEYLOGFILE to a file in its data folder; without the app nothing should keep writing keys there.
  if RegQueryStringValue(HKCU, 'Environment', 'SSLKEYLOGFILE', Keylog) and
     (Pos(Lowercase(DataDir), Lowercase(Keylog)) = 1) then
    RegDeleteValue(HKCU, 'Environment', 'SSLKEYLOGFILE');
  if DirExists(DataDir) and not UninstallSilent and
     (MsgBox(CustomMessage('DeleteData'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    DelTree(DataDir, True, True, True);
end;

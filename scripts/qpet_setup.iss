; QPet 桌面宠物 安装脚本 (Inno Setup)
#define MyAppName "Vivian 桌面宠物"
#define MyAppNameEn "Vivian Desktop Pet"
#define MyAppVersion "1.0.9"
#define MyAppExeName "QPet.exe"

[Setup]
AppId={{8F3C2A91-6D4E-4B7A-9C21-QPET2026DESK}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Louis_Qi
AppCopyright=Copyright (c) 2026 Louis_Qi. Designed for Vivian.
AppPublisherURL=https://github.com/qiban
AppSupportURL=https://github.com/qiban
DefaultDirName={localappdata}\QPet
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=QPet-Setup
SetupIconFile=..\assets\vivian.ico
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Messages]
SetupAppTitle=安装 - {#MyAppName}
WelcomeLabel1=欢迎安装 [name]
WelcomeLabel2=Designed by Louis_Qi for Vivian%n%n点击"下一步"继续安装，或点击"取消"退出。
ButtonBack=< 上一步(&B)
ButtonNext=下一步(&N) >
ButtonInstall=安装(&I)
ButtonFinish=完成(&F)
ButtonCancel=取消
ButtonBrowse=浏览(&R)...
SelectDirDesc=选择安装位置
SelectDirLabel3=安装程序将把 [name] 安装到以下文件夹。
SelectDirBrowseLabel=如需更换文件夹，请点击"浏览"。
SelectTasksDesc=选择附加任务
SelectTasksLabel2=选择安装程序要执行的附加任务，然后点击"下一步"。
ExitSetupTitle=退出安装
ExitSetupMessage=安装尚未完成。如果现在退出，程序将不会被安装。%n%n稍后可以重新运行安装程序完成安装。确定退出吗？
FinishedHeadingLabel=[name] 安装完成
FinishedLabelNoIcons=安装程序已在您的电脑上安装 [name]。点击"完成"结束安装。
FinishedRestartLabel=建议重启电脑以完成安装。
PreparingDesc=正在准备安装...
InstallingLabel=正在安装 [name]，请稍候...
UninstallAppTitle=卸载 - {#MyAppName}
UninstallAppFullTitle=卸载 [name]

[CustomMessages]
CreateDesktopIcon=创建桌面快捷方式
AutoStart=开机自动启动
RunAfter=立即运行 {#MyAppName}

[Files]
Source: "dist\QPet\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion createallsubdirs

[InstallDelete]
; 升级安装时删除旧桌面快捷方式，让 [Icons] 段重新生成（修复旧图标缓存）
Type: files; Name: "{autodesktop}\{#MyAppName}"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vivian.ico"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\vivian.ico"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "附加任务："
Name: "autorun"; Description: "{cm:AutoStart}"; GroupDescription: "附加任务："

[Registry]
; 勾选"开机自动启动"时写入 HKCU Run（与宠物设置面板中的开关是同一注册表项）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "QPetDesktopPet"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autorun

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:RunAfter}"; Flags: nowait postinstall skipifsilent unchecked

@echo off
REM ============================================================================
REM  Vivian 桌面宠物 - Windows 打包脚本 (V1.0.2)
REM  产出：scripts\dist\QPet\ + release\QPet-Setup.exe + release\Vivian-Pet-Portable-Windows.zip
REM
REM  需要：
REM    - Python 3.10+ with tkinter + PIL + PyInstaller
REM    - Inno Setup 6 (tools\InnoSetup\ISCC.exe)
REM ============================================================================

setlocal

set ROOT=%~dp0..
set SCRIPTS=%~dp0
set APPDIR=%ROOT%\app
set ASSETDIR=%ROOT%\assets
set DIST=%SCRIPTS%\dist
set BUILD=%SCRIPTS%\build
set RELEASE=%ROOT%\release
set PYEXE=

echo === Vivian 桌面宠物 Windows 打包 (V1.0.2) ===

REM 1) 选 Python：优先 mysoft/python314（有 tkinter），回退到系统 python
if exist D:\CodeTools\Mysoft\python314\python.exe (
    set "PYEXE=D:\CodeTools\Mysoft\python314\python.exe"
) else (
    set "PYEXE=python"
)

echo [1/5] Python: %PYEXE%
%PYEXE% --version

REM 2) 清理
echo [2/5] 清理旧构建...
if exist "%DIST%" rmdir /s /q "%DIST%"
if exist "%BUILD%" rmdir /s /q "%BUILD%"

REM 3) PyInstaller 打包
echo [3/5] PyInstaller 打包...
cd /d "%SCRIPTS%"
%PYEXE% -m PyInstaller --noconfirm --clean --windowed --name QPet --icon "%ASSETDIR%\vivian.ico" "%APPDIR%\qpet_app.py"
if errorlevel 1 goto :err

REM 4) 复制资源到 dist/QPet/
echo [4/5] 复制资源...
copy /Y "%ASSETDIR%\spritesheet.png"  "%DIST%\QPet\" >nul
copy /Y "%ASSETDIR%\pet.json"         "%DIST%\QPet\" >nul
copy /Y "%ASSETDIR%\vivian.ico"       "%DIST%\QPet\" >nul
copy /Y "%ASSETDIR%\vivian.png"       "%DIST%\QPet\" >nul
xcopy /E /I /Y "%ASSETDIR%\voicepacks" "%DIST%\QPet\voicepacks\" >nul

REM 5) 生成绿色版 zip
echo [5/5] 生成绿色版 + 安装包...
cd /d "%DIST%"
%PYEXE% -c "import shutil; shutil.make_archive('Vivian-Pet-Portable-Windows', 'zip', '.', 'QPet')"
move /Y "Vivian-Pet-Portable-Windows.zip" "%RELEASE%\" >nul

REM 编译 Inno Setup 安装包
set ISCC=%ROOT%\tools\InnoSetup\ISCC.exe
if exist "%ISCC%" (
    cd /d "%SCRIPTS%"
    "%ISCC%" qpet_setup.iss
) else (
    echo [warn] 未找到 Inno Setup (tools\InnoSetup\ISCC.exe)，跳过安装包生成
)

echo.
echo === 完成 ===
echo  exe:      %DIST%\QPet\QPet.exe
echo  zip:      %RELEASE%\Vivian-Pet-Portable-Windows.zip
echo  installer: %RELEASE%\QPet-Setup.exe
endlocal
goto :eof

:err
echo [error] PyInstaller 失败
endlocal
exit /b 1
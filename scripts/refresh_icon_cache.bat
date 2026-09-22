@echo off
chcp 65001 >nul
title 刷新 Windows 图标缓存 - Vivian 桌面宠物
echo.
echo  如果桌面快捷方式或任务栏图标显示为旧的默认图标，
echo  运行本脚本可以强制 Windows 重新生成图标缓存。
echo.
echo  即将执行以下操作：
echo    1. 关闭资源管理器
echo    2. 删除图标缓存数据库
echo    3. 重新启动资源管理器
echo.
pause

taskkill /f /im explorer.exe >nul 2>&1
timeout /t 2 /nobreak >nul
del /f /s /q /a "%LocalAppData%\IconCache.db" >nul 2>&1
del /f /s /q /a "%LocalAppData%\Microsoft\Windows\Explorer\iconcache_*.db" >nul 2>&1
start explorer.exe

echo.
echo  ✓ 图标缓存已刷新。桌面图标应该在几秒内恢复为 Vivian 艺术字图标。
echo  如果仍显示旧图标，请注销并重新登录一次。
echo.
pause
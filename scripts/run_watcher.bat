@echo off
chcp 65001 >nul
title IPTV直播源变动实时监听同步工具
cd /d "%~dp0\.."

echo ==================================================
echo       IPTV 直播源变动实时监听与自动触发工具
echo ==================================================
echo 提示: 检测到上游源有新比赛时，将立即调用 GitHub API
echo 触发 GitHub Actions 并在 10 秒内自动完成全量同步。
echo ==================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3 并勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

python scripts\watch_upstream.py %*
pause

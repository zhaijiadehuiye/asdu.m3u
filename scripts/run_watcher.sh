#!/usr/bin/env bash
# macOS / Linux / NAS / OpenWrt 一键启动监听脚本
# 可在前台运行，也可通过 nohup 在后台 7x24 小时常驻

cd "$(dirname "$0")/.." || exit 1

# 检查是否安装了 Python 3
if ! command -v python3 &>/dev/null; then
    echo "未检测到 python3，请先安装 Python 3。"
    exit 1
fi

echo "=================================================="
echo "      IPTV 直播源变动实时监听与自动触发工具"
echo "=================================================="
echo "提示: 检测到上游源有新比赛时，将立即调用 GitHub API"
echo "触发 GitHub Actions 并在 10 秒内自动完成全量同步。"
echo "=================================================="

# 启动监听脚本（每 60 秒轮询一次）
python3 scripts/watch_upstream.py "$@"

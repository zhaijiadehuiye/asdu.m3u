#!/usr/bin/env python3
"""
实时监听上游直播源变动，一旦检测到更新立即触发 GitHub Actions 同步。
支持本地常驻运行（例如配合 screen/systemd 或直接命令行启动）。

使用方式:
    python3 scripts/watch_upstream.py
    或者通过环境变量设置 Token:
    GH_TOKEN="你的GitHubToken" python3 scripts/watch_upstream.py --interval 60
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.request
from typing import Optional

DEFAULT_SOURCE_URL = "https://jsnzkpg.de5.net/all.m3u"
DEFAULT_REPO = "zhaijiadehuiye/asdu.m3u"
DEFAULT_WORKFLOW = "update.yml"


def get_upstream_hash(url: str, timeout: int = 15) -> tuple[Optional[str], Optional[int]]:
    """获取上游 M3U 内容的 MD5 哈希与字节长度"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "okhttp/4.12.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            if b"#EXTM3U" not in data:
                return None, None
            content_hash = hashlib.md5(data).hexdigest()
            return content_hash, len(data)
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 访问上游失败: {e}", file=sys.stderr)
        return None, None


def trigger_github_workflow(repo: str, workflow: str, token: str) -> bool:
    """调用 GitHub REST API 手动触发 workflow_dispatch"""
    api_url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    req = urllib.request.Request(
        api_url,
        data=json.dumps({"ref": "main"}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "upstream-watcher",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 成功触发 GitHub Actions 工作流: {workflow}")
                return True
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 触发返回状态码: {resp.status}", file=sys.stderr)
                return False
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 触发 GitHub Actions 失败: {e}", file=sys.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="监听上游直播源并自动触发 GitHub Actions 同步")
    parser.add_argument("--url", default=DEFAULT_SOURCE_URL, help="上游直播源 M3U 地址")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="GitHub 仓库 (owner/repo)")
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW, help="目标工作流文件名")
    parser.add_argument("--interval", type=int, default=60, help="轮询检测间隔（秒，默认 60）")
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""), help="GitHub Personal Access Token")
    parser.add_argument("--once", action="store_true", help="单次检测并退出")
    args = parser.parse_args()

    token = args.token.strip()
    if not token and not args.once:
        print("提示: 未检测到 GH_TOKEN。若检测到更新将仅输出通知，无法自动触发 GitHub API。")
        print("建议启动时传入: export GH_TOKEN='你的Token' 或 --token='你的Token'\n")

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始监听上游直播源: {args.url}")
    print(f"目标仓库: {args.repo} | 工作流: {args.workflow} | 检查间隔: {args.interval}s")

    last_hash, initial_len = get_upstream_hash(args.url)
    if last_hash:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 初始内容 Hash: {last_hash} ({initial_len} bytes)")
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 警告: 首次检测未获取到有效内容，将在下个周期重试")

    if args.once:
        return 0

    while True:
        try:
            time.sleep(args.interval)
            current_hash, current_len = get_upstream_hash(args.url)
            if not current_hash:
                continue

            if last_hash is None:
                last_hash = current_hash
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 记录基准 Hash: {current_hash}")
                continue

            if current_hash != last_hash:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🔔 检测到上游直播源更新！")
                print(f"   原 Hash: {last_hash} -> 新 Hash: {current_hash} (大小: {current_len} bytes)")
                last_hash = current_hash
                if token:
                    trigger_github_workflow(args.repo, args.workflow, token)
                else:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 未配置 Token，跳过 API 触发。")
            else:
                # 内容未变化，静默保持监听
                pass
        except KeyboardInterrupt:
            print("\n监听已停止。")
            break


if __name__ == "__main__":
    sys.exit(main())

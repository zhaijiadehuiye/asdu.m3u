#!/usr/bin/env python3
"""
实时监听上游直播源变动，一旦检测到更新立即触发 GitHub Actions 同步。
纯 Python 3 标准库编写，无需安装任何第三方库（无需 pip install）。
支持 Windows、macOS、Linux、群晖/威联通 NAS、OpenWrt 软路由及 Docker。

使用方式:
    1. 最简运行（首次运行会提示输入 Token 并自动保存在本地 .watcher_token）:
       python3 scripts/watch_upstream.py

    2. 命令行传入 Token:
       python3 scripts/watch_upstream.py --token "你的GitHubToken"

    3. 环境变量传入 Token:
       GH_TOKEN="你的GitHubToken" python3 scripts/watch_upstream.py --interval 60

    4. 启动后立即触发一次同步测试:
       python3 scripts/watch_upstream.py --sync-now
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

DEFAULT_SOURCE_URL = "https://jsnzkpg.de5.net/all.m3u"
DEFAULT_REPO = "zhaijiadehuiye/asdu.m3u"
DEFAULT_WORKFLOW = "update.yml"
TOKEN_FILE = ".watcher_token"


def resolve_token(arg_token: Optional[str] = None) -> str:
    """按优先级获取 GitHub Token: 参数 > 环境变量 > 本地 .watcher_token > 交互式输入"""
    if arg_token and arg_token.strip():
        return arg_token.strip()

    env_token = os.environ.get("GH_TOKEN", "").strip()
    if env_token:
        return env_token

    # 检查当前目录及脚本同级目录下的 .watcher_token
    search_paths = [
        Path.cwd() / TOKEN_FILE,
        Path(__file__).resolve().parent / TOKEN_FILE,
        Path(__file__).resolve().parent.parent / TOKEN_FILE,
    ]
    for p in search_paths:
        if p.exists():
            try:
                saved = p.read_text(encoding="utf-8").strip()
                if saved:
                    return saved
            except Exception:
                pass

    # 若终端可交互，提示用户输入并保存
    if sys.stdin.isatty():
        print("\n" + "=" * 60)
        print("【首次配置】未检测到 GitHub Token。")
        print("请输入你的 GitHub Personal Access Token (PAT):")
        print("（Token 仅保存在本地 .watcher_token 文件中，已加入 .gitignore，绝不会上传）")
        print("=" * 60)
        try:
            user_input = input("请输入 GitHub Token: ").strip()
            if user_input:
                try:
                    save_path = Path.cwd() / TOKEN_FILE
                    save_path.write_text(user_input, encoding="utf-8")
                    save_path.chmod(0o600)  # 仅当前用户可读写
                    print(f"Token 已安全保存至: {save_path.resolve()}\n")
                except Exception as e:
                    print(f"本地保存 Token 失败: {e}，本次将仅在内存中使用。")
                return user_input
        except (KeyboardInterrupt, EOFError):
            print("\n已取消输入。")
            sys.exit(1)

    return ""


def verify_token(token: str) -> Optional[str]:
    """校验 Token 是否有效，并返回关联的 GitHub 用户名"""
    if not token:
        return None
    api_url = "https://api.github.com/user"
    req = urllib.request.Request(
        api_url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "m3u-watcher",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("login", "unknown")
    except Exception as e:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Token 校验失败: {e}", file=sys.stderr)
        return None


def get_upstream_hash(url: str, timeout: int = 15) -> Tuple[Optional[str], Optional[int]]:
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
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 访问上游源失败: {e}", file=sys.stderr)
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
            "User-Agent": "m3u-watcher",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status in (200, 204):
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🚀 成功触发 GitHub Actions 工作流: {workflow}！仓库正在抓取并同步最新列表...")
                return True
            else:
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 触发返回异常状态码: {resp.status}", file=sys.stderr)
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
    parser.add_argument("--token", default=None, help="GitHub Personal Access Token")
    parser.add_argument("--sync-now", action="store_true", help="启动时立即触发一次同步")
    parser.add_argument("--once", action="store_true", help="单次检测并退出")
    args = parser.parse_args()

    token = resolve_token(args.token)
    if token:
        username = verify_token(token)
        if username:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ✓ GitHub Token 认证成功，用户: @{username}")
        else:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ⚠️ 警告: Token 认证未通过，请检查 Token 是否有效或网络是否通畅")
    else:
        if not args.once:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] ⚠️ 提示: 未配置 Token，将仅输出变动通知，不会自动调用 GitHub API 同步。")

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 开始监听上游直播源: {args.url}")
    print(f"目标仓库: {args.repo} | 工作流: {args.workflow} | 检查间隔: {args.interval}s")

    if args.sync_now and token:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 正在执行启动立即同步测试...")
        trigger_github_workflow(args.repo, args.workflow, token)

    last_hash, initial_len = get_upstream_hash(args.url)
    if last_hash:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 初始基准 Hash: {last_hash} ({initial_len} bytes)")
    else:
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 警告: 首次检测未拉取到内容，将在下个周期继续尝试")

    if args.once:
        return 0

    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 持续监听中 (按 Ctrl+C 退出)...")
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
                print(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] 🔔 检测到上游直播源更新！")
                print(f"   原 Hash: {last_hash} -> 新 Hash: {current_hash} (大小: {current_len} bytes)")
                last_hash = current_hash
                if token:
                    trigger_github_workflow(args.repo, args.workflow, token)
                else:
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 未配置 Token，跳过 API 触发。")
            else:
                # 内容未变动，保持静默监听
                pass
        except KeyboardInterrupt:
            print("\n监听已停止。")
            break
        except Exception as e:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 运行异常: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    sys.exit(main())

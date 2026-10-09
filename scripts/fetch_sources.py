#!/usr/bin/env python3
"""Extract public, non-DRM HLS/M3U sources from timst.top pages or feeds."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
import os
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

DEFAULT_URL = "https://timst.top/live-tv"
DEFAULT_API = ("https://timst.top/api/channels", "https://timst.top/api/live-upcoming")
URL_RE = re.compile(r'''https?://[^"'<>\s]+''', re.I)
STREAM_RE = re.compile(r"\.(?:m3u8?|mpd)(?:[?#]|$)", re.I)
KEY_RE = re.compile(r"(?:m3u8?|stream|source|manifest|playlist|file|url)", re.I)
# The page randomizes these variable names on each response. Restrict the
# decoder to numeric arrays and the same XOR/offset shape used by the player.
OBFUSCATED_RE = re.compile(
    r"var\s+_[A-Za-z0-9]+\s*=\[((?:\s*\d+\s*,?)+)\],"
    r"_[A-Za-z0-9]+\s*=\s*(\d+),_[A-Za-z0-9]+\s*=\s*(\d+),_[A-Za-z0-9]+\s*=\s*",
    re.S,
)


class PageParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.items: list[tuple[str, str]] = []
        self._stack: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_d = {k.lower(): v for k, v in attrs if v is not None}
        title = next((attrs_d.get(k) for k in ("aria-label", "title", "data-title", "alt") if attrs_d.get(k)), "")
        self._stack.append((tag, []))
        for key in ("href", "src", "data-src", "data-url", "data-stream", "data-m3u8", "content"):
            value = attrs_d.get(key)
            if value and STREAM_RE.search(value):
                self.items.append((urljoin(self.base_url, html.unescape(value)), title))

    def handle_data(self, data: str) -> None:
        if self._stack:
            self._stack[-1][1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self._stack:
            return
        # Use nearby anchor text as a channel label.
        if self._stack[-1][0] == tag:
            _, text = self._stack.pop()
            label = " ".join("".join(text).split())
            if label:
                for i in range(len(self.items) - 1, -1, -1):
                    url, old = self.items[i]
                    if not old:
                        self.items[i] = (url, label)
                        break


def fetch(url: str, timeout: int = 20) -> tuple[str, str]:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; timst-live-tv/1.0)"})
    with urlopen(req, timeout=timeout) as response:
        raw = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace"), response.headers.get("Content-Type", "")


def walk_json(value: Any, base_url: str, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        label = str(next((value.get(k) for k in ("name", "title", "channel", "label") if value.get(k)), ""))
        for key, item in value.items():
            if isinstance(item, str) and STREAM_RE.search(item) and KEY_RE.search(key):
                out.append((urljoin(base_url, html.unescape(item)), label))
            else:
                walk_json(item, base_url, out)
    elif isinstance(value, list):
        for item in value:
            walk_json(item, base_url, out)


def candidates(text: str, base_url: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    parser = PageParser(base_url)
    try:
        parser.feed(text)
        out.extend(parser.items)
    except Exception:
        pass
    for match in URL_RE.finditer(text):
        url = html.unescape(match.group(0)).rstrip("\\),;\"")
        if STREAM_RE.search(url):
            before = text[max(0, match.start() - 180):match.start()]
            label_match = re.search(r"(?:title|name|channel|label)\s*[:=]\s*[\"']([^\"']+)", before, re.I)
            out.append((urljoin(base_url, url), label_match.group(1).strip() if label_match else ""))
    # Some feeds are JSON documents with escaped URLs.
    try:
        walk_json(json.loads(text), base_url, out)
    except Exception:
        pass
    # TimStreams' intermediary pages currently place a signed HLS URL inside
    # an openly embedded, XOR/offset-obfuscated script. Decode only that page
    # data; do not execute the script or bypass its player/authentication.
    for match in OBFUSCATED_RE.finditer(text):
        try:
            values = [int(item) for item in match.group(1).split(",") if item.strip()]
            key = int(match.group(2))
            offset = int(match.group(3))
            decoded = "".join(chr(((value ^ key) - offset + 256) % 256) for value in values)
            out.extend(candidates(decoded, base_url))
        except (ValueError, OverflowError):
            continue
    return out


def api_streams(value: Any, out: list[tuple[str, str]]) -> None:
    """Extract stream links from TimStreams' public JSON response."""
    if isinstance(value, dict):
        label = str(next((value.get(k) for k in ("name", "title", "channel", "label") if value.get(k)), "Timst TV"))
        streams = value.get("streams")
        if isinstance(streams, list):
            for stream in streams:
                if isinstance(stream, dict) and isinstance(stream.get("url"), str):
                    out.append((stream["url"], label))
        for item in value.values():
            api_streams(item, out)
    elif isinstance(value, list):
        for item in value:
            api_streams(item, out)


def resolve_stream_page(url: str, label: str, timeout: int, errors: list[str], depth: int = 0) -> list[tuple[str, str]]:
    """Resolve one public intermediary page, without bypassing access controls."""
    if depth > 2:
        return []
    try:
        body, content_type = fetch(url, timeout)
        if body.lstrip().startswith("#EXTM3U"):
            return [(entry[0], label or entry[1]) for entry in parse_m3u(body, url)]
        direct = [(stream, label or stream_label) for stream, stream_label in candidates(body, url)]
        if direct:
            return direct
        # A public embed may point at a second player page; follow only iframe
        # and video source links and keep the recursion shallow.
        embeds = re.findall(r"<(?:iframe|video|source)[^>]+(?:src|data-src)=[\"']([^\"']+)", body, re.I)
        resolved: list[tuple[str, str]] = []
        for embed in embeds[:5]:
            target = urljoin(url, html.unescape(embed))
            if target != url:
                resolved.extend(resolve_stream_page(target, label, timeout, errors, depth + 1))
        return resolved
    except Exception as exc:
        errors.append(f"{url}: {exc}")
        return []


def parse_m3u(text: str, base_url: str) -> list[tuple[str, str, str, str]]:
    lines = [line.strip() for line in text.splitlines()]
    result: list[tuple[str, str, str, str]] = []
    pending = ""
    attrs = ""
    for line in lines:
        if line.startswith("#EXTINF"):
            attrs = line
            pending = line.rsplit(",", 1)[-1].strip() if "," in line else ""
        elif line and not line.startswith("#") and re.match(r"https?://", line):
            result.append((urljoin(base_url, line), pending or "Timst TV", attrs, "m3u"))
            pending = ""
            attrs = ""
    return result


def attrs_for(name: str, source: str, original: str, index: int) -> str:
    safe = re.sub(r"[\r\n\"]", "", name).strip() or f"Timst TV {index:03d}"
    host = urlparse(source).hostname or "timst.top"
    return f'#EXTINF:-1 tvg-name="{safe}" group-title="Timst TV" source="{host}",{safe}'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("TIMST_PAGE_URL", DEFAULT_URL))
    ap.add_argument("--api", action="append", default=list(DEFAULT_API), help="Public TimStreams JSON endpoint; repeatable")
    ap.add_argument("--feed", action="append", default=[], help="Optional public feed/API URL; repeatable")
    ap.add_argument("--no-resolve-pages", action="store_true", help="Do not follow public intermediary stream pages")
    ap.add_argument("--workers", type=int, default=12, help="Concurrent intermediary page fetches")
    ap.add_argument("--output", default="generated/timst.m3u")
    ap.add_argument("--report", default="reports/last-run.json")
    ap.add_argument("--timeout", type=int, default=20)
    args = ap.parse_args()

    fetched: list[dict[str, Any]] = []
    found: list[tuple[str, str]] = []
    errors: list[str] = []
    urls = [args.url, *args.api, *args.feed]
    for url in urls:
        try:
            body, content_type = fetch(url, args.timeout)
            fetched.append({"url": url, "status": "ok", "bytes": len(body), "content_type": content_type})
            if body.lstrip().startswith("#EXTM3U"):
                found.extend((x[0], x[1]) for x in parse_m3u(body, url))
            elif "/api/" in url:
                data = json.loads(body)
                api_found: list[tuple[str, str]] = []
                api_streams(data, api_found)
                found.extend(api_found)
            else:
                found.extend(candidates(body, url))
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            fetched.append({"url": url, "status": "error", "error": str(exc)})

    # TimStreams' API intentionally returns public intermediary player pages
    # (for example grandemx.org). Resolve those pages to actual HLS URLs when
    # possible; retain no intermediary page as a playlist entry.
    resolved_found: list[tuple[str, str]] = []
    page_targets: dict[str, str] = {}
    for url, label in found:
        if STREAM_RE.search(url) or args.no_resolve_pages:
            resolved_found.append((url, label))
        elif urlparse(url).scheme in ("http", "https"):
            page_targets.setdefault(url, label)
    if page_targets:
        workers = max(1, min(args.workers, len(page_targets)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            jobs = {pool.submit(resolve_stream_page, url, label, args.timeout, errors): url for url, label in page_targets.items()}
            for job in as_completed(jobs):
                resolved_found.extend(job.result())

    dedup: dict[str, str] = {}
    for url, label in resolved_found:
        if STREAM_RE.search(url) and urlparse(url).scheme in ("http", "https"):
            dedup.setdefault(url, label)
    entries = []
    skipped_drm = 0
    for i, (url, label) in enumerate(dedup.items(), 1):
        if url.lower().split("?", 1)[0].endswith(".mpd"):
            skipped_drm += 1
            continue
        entries.append((url, label))

    out = ["#EXTM3U", "# Generated from public page/feed data; refresh to update expiring URLs."]
    for i, (url, label) in enumerate(entries, 1):
        out.append(attrs_for(label, url, url, i))
        if urlparse(url).hostname == "judiaslevels.embeds.gay":
            # The source is normally embedded by grandemx.org. Players that
            # support VLC options can preserve that normal referrer context.
            out.append("#EXTVLCOPT:http-referrer=https://grandemx.org/")
            out.append("#EXTVLCOPT:http-user-agent=Mozilla/5.0")
        out.append(url)
    # Never erase a previously generated playlist solely because the source is
    # temporarily unavailable or returned no usable streams.
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if entries or not output_path.exists():
        output_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    report = {"generated_at": int(time.time()), "inputs": fetched, "entries": len(entries), "skipped_mpd": skipped_drm, "errors": errors}
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if entries else 2


if __name__ == "__main__":
    raise SystemExit(main())

# Timst Live TV sources

This branch adds a generated M3U source for publicly exposed, non-DRM streams linked by [timst.top/live-tv](https://timst.top/live-tv). The site currently exposes its catalogue through `/api/channels` and `/api/live-upcoming`; those responses point at public intermediary player pages, which the extractor follows to locate HLS URLs.

The extractor only follows normal HTTP(S) page/feed data. It does not bypass DRM, authentication, geo restrictions, or paywalls. Timst currently embeds signed HLS URLs in its public player page; those URLs expire, so the generated playlist must be refreshed regularly and may require the source site's normal referrer policy in the player's requests.

## Refresh locally

```sh
python3 scripts/fetch_sources.py --url https://timst.top/live-tv
```

An optional public feed/API can be supplied with `--feed URL`; the default TimStreams API endpoints are already included. The output is `generated/timst.m3u`; the diagnostic report is `reports/last-run.json`. A run exits with status 2 when no usable stream is found and retains the previous generated playlist. `--no-resolve-pages` is available for diagnostics, but intermediary player-page URLs are deliberately excluded from the generated playlist. The generated entries include VLC referrer/user-agent hints for the current `judiaslevels.embeds.gay` source host; players may ignore those hints.

## Automation

The default-branch workflow runs every 15 minutes, validates the generated M3U syntax, and commits only changed generated files to this branch. GitHub scheduled workflows run from the default branch, so the scheduler is stored under `main` while this branch holds the generated playlist. The runner needs HTTPS access to `timst.top` and the intermediary hosts returned by its API (currently `grandemx.org`; this can change). Signed URLs are intentionally refreshed rather than treated as permanent. The current playlist is available at `https://raw.githubusercontent.com/zhaijiadehuiye/asdu.m3u/timst-live-tv/generated/timst.m3u`. Keep page/feed URLs and any required non-secret configuration in the workflow, never credentials in the repository.

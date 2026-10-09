# Timst Live TV sources

This repository is a generated M3U source for publicly exposed, non-DRM streams linked by [timst.top/live-tv](https://timst.top/live-tv). The site currently exposes its catalogue through `/api/channels` and `/api/live-upcoming`; those responses point at public intermediary player pages, which the extractor follows to locate HLS URLs.

The extractor only follows normal HTTP(S) page/feed data. It does not bypass DRM, authentication, geo restrictions, paywalls, or signed URL protection. HLS URLs may expire, so the generated playlist should be refreshed before use.

## Refresh locally

```sh
python3 scripts/fetch_sources.py --url https://timst.top/live-tv
```

An optional public feed/API can be supplied with `--feed URL`; the default TimStreams API endpoints are already included. The output is `generated/timst.m3u`; the diagnostic report is `reports/last-run.json`. A run exits with status 2 when no usable stream is found and retains the previous generated playlist. `--no-resolve-pages` is available for diagnostics, but intermediary player-page URLs are deliberately excluded from the generated playlist.

## Automation

A scheduled job can run the command, validate the generated M3U syntax, and commit only changed generated files. The runner needs HTTPS access to `timst.top` and the intermediary hosts returned by its API (currently `grandemx.org`; this can change). Keep page/feed URLs and any required non-secret configuration in the workflow, never credentials in the repository.

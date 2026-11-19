"""Write website/release.json from the GitHub releases API.

Run from the repository root or the website directory:

    python -I website/update_release.py

The site reads this file at runtime. It is deliberately fail-soft: if GitHub
cannot be reached, or the API rate limit is exhausted, the existing
release.json is left untouched and the command exits 0 so a deploy can still
publish the last known data.

No third-party packages are required.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "release.json")
APP_REPO = "spedagadi/unplugged-mpc-hc"
RENDERER_REPO = "spedagadi/unplugged-VideoRenderer"
REPOS = (APP_REPO, RENDERER_REPO)
API = "https://api.github.com/repos/%s/releases?per_page=100"


def fetch_releases(repo):
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "unplugged-website",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(API % repo, headers=headers)
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.load(response)
    if not isinstance(data, list) or not data:
        raise ValueError("GitHub returned no releases for " + repo)
    return data


def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def version_of(tag):
    return tag[1:] if tag.startswith("v") else tag


def sha256_of(asset, body):
    digest = str(asset.get("digest") or "")
    match = re.search(r"sha256:([0-9a-fA-F]{64})", digest)
    if match:
        return match.group(1).upper()
    # Older releases may not expose the digest field. The release notes carry
    # the same hash, so use that as a fallback rather than downloading 127 MB.
    match = re.search(r"\b([0-9a-fA-F]{64})\b", str(body or ""))
    return match.group(1).upper() if match else ""


def pick_asset(release):
    assets = [asset for asset in (release.get("assets") or []) if asset.get("name")]
    for asset in assets:
        name = str(asset.get("name", "")).lower()
        if "setup" in name and name.endswith(".exe"):
            return asset
    for asset in assets:
        if str(asset.get("name", "")).lower().endswith(".exe"):
            return asset
    return assets[0] if assets else {}


def release_record(release, repo):
    tag = str(release.get("tag_name") or "")
    version = version_of(tag)
    asset = pick_asset(release)
    size = int(asset.get("size") or 0)
    downloads = sum(int(item.get("download_count") or 0) for item in (release.get("assets") or []))
    return {
        "repo": repo,
        "tag": tag,
        "version": version,
        "name": release.get("name") or tag,
        "publishedAt": release.get("published_at"),
        "releaseUrl": release.get("html_url"),
        "downloadUrl": asset.get("browser_download_url") or release.get("html_url"),
        "assetName": asset.get("name") or "",
        "assetSize": size,
        "sizeMB": int(round(size / 1_000_000)) if size else 0,
        "sha256": sha256_of(asset, release.get("body")),
        "downloads": downloads,
        "prerelease": bool(release.get("prerelease")),
    }


def build_payload(releases_by_repo):
    by_repo = {}
    all_records = []
    for repo, releases in releases_by_repo.items():
        records = [
            release_record(release, repo)
            for release in releases
            if not release.get("draft") and release.get("published_at")
        ]
        by_repo[repo] = records
        all_records.extend(records)

    app_records = by_repo.get(APP_REPO) or []
    if not app_records:
        raise ValueError("No published releases found for " + APP_REPO)
    if not all_records:
        raise ValueError("No published releases found")

    app_records.sort(key=lambda item: item.get("publishedAt") or "", reverse=True)
    stable = [item for item in app_records if not item.get("prerelease")]
    latest = stable[0] if stable else app_records[0]

    all_records.sort(key=lambda item: item.get("publishedAt") or "", reverse=True)
    first = min(all_records, key=lambda item: item.get("publishedAt") or "")
    total_downloads = sum(item.get("downloads", 0) for item in all_records)

    return {
        "generatedAt": iso_now(),
        "source": "https://github.com/%s/releases" % APP_REPO,
        "sources": ["https://github.com/%s/releases" % repo for repo in REPOS],
        "latest": latest,
        "releases": all_records,
        "totals": {
            "downloads": total_downloads,
            "releases": len(all_records),
            "firstReleaseDate": first.get("publishedAt"),
            "byRepo": {
                repo: {
                    "downloads": sum(item.get("downloads", 0) for item in records),
                    "releases": len(records),
                }
                for repo, records in by_repo.items()
            },
        },
    }


def main():
    try:
        releases_by_repo = {}
        for repo in REPOS:
            try:
                releases_by_repo[repo] = fetch_releases(repo)
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as error:
                if repo == APP_REPO:
                    raise
                print("release data: skipping %s (%s)" % (repo, error))
                releases_by_repo[repo] = []
        payload = build_payload(releases_by_repo)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError, OSError) as error:
        print("release data: keeping the existing release.json (%s)" % error)
        return 0

    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    previous = None
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as handle:
            previous = handle.read()
    if text == previous:
        print("release data: unchanged")
        return 0

    temporary = OUT + ".tmp"
    with open(temporary, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    os.replace(temporary, OUT)
    latest = payload["latest"]
    print(
        "release data: %s, %s bytes, %d downloads, %d releases"
        % (latest["version"], latest["assetSize"], payload["totals"]["downloads"], payload["totals"]["releases"])
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
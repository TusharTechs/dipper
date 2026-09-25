"""Fetch a small, openly licensed evaluation set of stream and outfall photos from Wikimedia Commons.

Only CC0, public-domain, CC BY and CC BY-SA files are kept. Each file's source page, author and
licence are recorded in data/eval/candidates.json for attribution. Images are downloaded at 1280 px
to data/eval/photos/ (gitignored). Labels are added separately, by looking at each photo.

    uv run python scripts/fetch_eval_photos.py
"""

from __future__ import annotations

import html
import json
import re
import time
from pathlib import Path

import httpx

API = "https://commons.wikimedia.org/w/api.php"
UA = {"User-Agent": "DipperHackathonEval/0.1 (OneAquaHealth hackathon prototype; research use)"}
OUT = Path(__file__).resolve().parents[1] / "data" / "eval"
OPEN = re.compile(r"^(cc0|public domain|pd|cc by(-sa)? [0-9.]+)", re.I)

# (search query, intended bucket, how many to keep)
QUERIES = [
    ("sewage outfall river pipe", "outfall", 5),
    ("storm drain outfall stream discharge", "outfall", 3),
    ("foam river pollution", "foam", 3),
    ("algal bloom green water river", "green", 3),
    ("muddy river flood brown water", "turbid", 3),
    ("clear forest stream", "clean", 3),
    ("urban stream park", "clean", 2),
]


def search(q: str, limit: int) -> list[dict]:
    r = httpx.get(API, headers=UA, timeout=30, params={
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"filetype:bitmap {q}",
        "gsrnamespace": 6, "gsrlimit": 25, "prop": "imageinfo", "iiprop": "url|extmetadata|mime|size",
        "iiurlwidth": 1280})
    r.raise_for_status()
    pages = sorted(r.json().get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        meta = ii.get("extmetadata", {})
        lic = meta.get("LicenseShortName", {}).get("value", "")
        if ii.get("mime") != "image/jpeg" or not OPEN.match(lic) or ii.get("width", 0) < 800:
            continue
        artist = re.sub(r"<[^>]+>", "", html.unescape(meta.get("Artist", {}).get("value", ""))).strip()
        out.append({"title": p["title"], "page": ii.get("descriptionurl"), "thumb": ii.get("thumburl"),
                    "license": lic, "license_url": meta.get("LicenseUrl", {}).get("value"), "author": artist[:120]})
        if len(out) == limit:
            break
    return out


def main() -> None:
    (OUT / "photos").mkdir(parents=True, exist_ok=True)
    seen, rows = set(), []
    for q, bucket, n in QUERIES:
        for item in search(q, n + 3):
            if item["title"] in seen or sum(r["bucket"] == bucket and r["query"] == q for r in rows) >= n:
                continue
            seen.add(item["title"])
            fid = f"{bucket}-{len([r for r in rows if r['bucket'] == bucket]) + 1:02d}"
            resp = httpx.get(item["thumb"], headers=UA, timeout=60, follow_redirects=True)
            data = resp.content
            if not resp.headers.get("content-type", "").startswith("image/") or data[:2] != b"\xff\xd8":
                print(f"skip {item['title']}: not a JPEG (HTTP {resp.status_code})")
                continue
            (OUT / "photos" / f"{fid}.jpg").write_bytes(data)
            rows.append({"id": fid, "bucket": bucket, "query": q, "bytes": len(data), **item})
            time.sleep(1.0)
        time.sleep(1.5)
    (OUT / "candidates.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"{len(rows)} photos, {sum(r['bytes'] for r in rows) / 1e6:.1f} MB")
    for r in rows:
        print(f"{r['id']:10} {r['license']:14} {r['title'][:70]}")


if __name__ == "__main__":
    main()

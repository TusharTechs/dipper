"""Photo retention: redacted photos are deleted after DIPPER_MEDIA_DAYS (default 30).

Runs at startup and at most hourly after a photo is stored, so the promise made to citizens holds without a
separate cron job. `python -m dipper_api.admin purge-media --days N` runs it by hand with a stricter limit."""
from __future__ import annotations

import os
import time
from pathlib import Path

MEDIA_DAYS = int(os.getenv("DIPPER_MEDIA_DAYS", "30"))
_last = 0.0


def purge_media(media: Path, days: int = MEDIA_DAYS) -> int:
    """Delete stored photos older than `days`. Returns how many were removed."""
    if not media.exists():
        return 0
    cutoff, removed = time.time() - days * 86400, 0
    for f in media.glob("*.jpg"):
        if f.stat().st_mtime < cutoff:
            f.unlink(missing_ok=True)
            removed += 1
    return removed


def maybe_purge(media: Path, every_s: float = 3600) -> None:
    global _last
    if time.monotonic() - _last >= every_s:
        _last = time.monotonic()
        purge_media(media)

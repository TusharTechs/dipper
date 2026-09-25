"""Evaluate photo feature extraction on the labelled Wikimedia Commons set.

Every photo goes through the production path: redact() first, then the configured vision provider.
Raw model outputs are cached in data/eval/results-<provider>.json so metrics can be recomputed
without new API calls. Writes data/eval/report-<provider>.md.

    uv run python scripts/eval_photos.py            # uses DIPPER_VISION_PROVIDER / configured key
    uv run python scripts/eval_photos.py --rescore  # recompute from cached outputs only
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "eval"
load_dotenv(ROOT / ".env")

from dipper_engine.photo import (  # noqa: E402
    GEMINI_MODEL, DEFAULT_MODEL, PHOTO_EXCLUDED, PRESENT_AT, PhotoFeatures, PhotoModelUnavailable, extract, redact,
    to_observation, vision_provider,
)


def run(provider: str, cache: Path) -> dict:
    out = json.loads(cache.read_text()) if cache.exists() else {}
    labels = json.loads((EVAL / "labels.json").read_text())["labels"]
    for pid in labels:
        if pid in out and "features" in out[pid]:
            continue
        red = redact((EVAL / "photos" / f"{pid}.jpg").read_bytes())
        for attempt in range(4):
            try:
                t = time.time()
                pf = extract(red.jpeg)
                out[pid] = {"features": pf.model_dump(), "seconds": round(time.time() - t, 2)}
                break
            except PhotoModelUnavailable as exc:
                out[pid] = {"error": str(exc)}
                if "rate" not in str(exc) and "429" not in str(exc):
                    break
                time.sleep(10 * (attempt + 1))
        print(f"{pid:12} {'ok' if 'features' in out[pid] else out[pid]['error']}")
        cache.write_text(json.dumps(out, indent=2))
        time.sleep(1.0)
    return out


def score(results: dict) -> dict:
    lab = json.loads((EVAL / "labels.json").read_text())
    feats, labels = lab["features"], lab["labels"]
    per = {f: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for f in feats}
    scope = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    img = {"polluted_detected": 0, "polluted_total": 0, "clean_false_alarms": 0, "clean_total": 0}
    errors, mistakes, secs = [], [], []
    for pid, truth in labels.items():
        r = results.get(pid, {})
        if "features" not in r:
            errors.append(pid)
            continue
        secs.append(r["seconds"])
        pf = PhotoFeatures.model_validate(r["features"])
        obs = to_observation(pf, "n")
        admitted = obs is not None
        key = ("t" if truth["in_scope"] else "f") + ("p" if admitted else "n")
        scope[{"tp": "tp", "tn": "fn", "fp": "fp", "fn": "tn"}[key]] += 1  # tp: in scope & admitted
        if not truth["in_scope"]:
            if admitted:
                mistakes.append(f"{pid}: out-of-scope image admitted as evidence ({truth['note']})")
            continue
        if not admitted:
            mistakes.append(f"{pid}: in-scope photo rejected ({truth['note']}); model note: {pf.note}")
        calls = pf.calls()
        for f in feats:
            want = truth["features"].get(f)
            if want is None or f in PHOTO_EXCLUDED:
                continue
            c = calls[f]
            got = admitted and c.present and c.confidence >= PRESENT_AT
            per[f]["tp" if want and got else "fn" if want else "fp" if got else "tn"] += 1
            if want != got:
                mistakes.append(f"{pid}: {f} expected {want}, got {got} (conf {c.confidence:.2f}) - {truth['note']}")
        used = {f: v for f, v in truth["features"].items() if f not in PHOTO_EXCLUDED}
        polluted = any(v for v in used.values())
        clean = all(v is False for v in used.values())
        positive = bool(obs and obs.positive)
        if polluted:
            img["polluted_total"] += 1
            img["polluted_detected"] += positive
        if clean:
            img["clean_total"] += 1
            img["clean_false_alarms"] += positive
    return {"per_feature": per, "scope": scope, "image": img, "errors": errors, "mistakes": mistakes,
            "median_seconds": sorted(secs)[len(secs) // 2] if secs else None, "n": len(labels)}


def pct(a: int, b: int) -> str:
    return "–" if b == 0 else f"{100 * a / b:.0f}% ({a}/{b})"


def report(s: dict, provider: str, model: str) -> str:
    lines = [f"# Photo feature evaluation · {provider} ({model})", "",
             f"{s['n']} Wikimedia Commons photos (openly licensed; sources in `candidates.json`), labelled by the "
             "developer from each photo and its Commons description. **Not expert-verified; small sample.** Every "
             "photo went through `redact()` first, exactly as in production. A feature counts as present at "
             f"confidence ≥ {PRESENT_AT}. Features not used from photos: {', '.join(sorted(PHOTO_EXCLUDED)) or 'none'}.", "",
             "## Image level", "",
             f"- Polluted photos that produced a positive observation: **{pct(s['image']['polluted_detected'], s['image']['polluted_total'])}**",
             f"- Clean photos that produced a false alarm: **{pct(s['image']['clean_false_alarms'], s['image']['clean_total'])}**",
             f"- Out-of-scope images (satellite, no water) correctly kept out of the evidence: "
             f"**{pct(s['scope']['tn'], s['scope']['tn'] + s['scope']['fp'])}**",
             f"- In-scope photos admitted as evidence: **{pct(s['scope']['tp'], s['scope']['tp'] + s['scope']['fn'])}**",
             f"- Median model latency: {s['median_seconds']} s · errors: {len(s['errors'])}", "",
             "## Per feature (in-scope photos, ambiguous labels excluded)", "",
             "| Feature | Recall | Precision | False positives on negatives |", "|---|---|---|---|"]
    for f, c in s["per_feature"].items():
        lines.append(f"| {f} | {pct(c['tp'], c['tp'] + c['fn'])} | {pct(c['tp'], c['tp'] + c['fp'])} | "
                     f"{pct(c['fp'], c['fp'] + c['tn'])} |")
    lines += ["", "## Disagreements", ""] + [f"- {m}" for m in s["mistakes"]] + [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true")
    args = ap.parse_args()
    provider = vision_provider()
    model = GEMINI_MODEL if provider == "gemini" else DEFAULT_MODEL
    cache = EVAL / f"results-{provider}.json"
    results = json.loads(cache.read_text()) if args.rescore else run(provider, cache)
    s = score(results)
    md = report(s, provider, model)
    (EVAL / f"report-{provider}.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()

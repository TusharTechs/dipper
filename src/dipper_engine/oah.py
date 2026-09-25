"""Adapter for OneAquaHealth Citizen Science App submissions.

The OAH app (apps.oneaquahealth.eu, v1.0) asks, among its stream-assessment questions:
  water_flow        Fast (A) | Slow (B) | Stagnant/intermittent (C) | Dry (D) | I am not sure
  water_aspect      Clear/transparent (A) | Muddy/turbid (B) | Has foam (C) | Has colors/altered color (D) | I am not sure
  draining_pipes    "Are there pipes draining polluted water into the stream?"  Yes | No | I am not sure
  sewage_discharge  "Is there any kind of water entry or discharge of sewage?"   Yes | No | I am not sure
Option labels come from the app's public interface text. The submission JSON field names used here follow
those question keys and must be confirmed against the ENORA back-end API before production use.

Mapping to Dipper evidence:
  * any pollution answer (turbid, foam, altered colour, polluted pipe, sewage) → a positive citizen report
  * clear water with no pipe or sewage answer → a clean look at that point (routine assessments help too)
  * "I am not sure", missing answers, or a dry stream → no evidence
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .belief import Observation

NOT_SURE = {"i am not sure", "i'm not sure", "not sure", ""}


def _norm(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return " | ".join(_norm(x) for x in v)
    s = str(v).strip().lower()
    return s.replace("(α)", "(a)").replace("(β)", "(b)")  # the app ships Greek-letter variants of option codes


def _choice(v: Any) -> set[str]:
    """Normalised option set from a label ('Has foam (C)'), a code ('C') or a list of either."""
    raw = v if isinstance(v, list) else [v]
    out = set()
    for item in raw:
        s = _norm(item)
        if s in NOT_SURE:
            continue
        code = s[-2] if s.endswith(")") and len(s) >= 3 and s[-3] == "(" else s if len(s) == 1 else ""
        out.add(code or s)
    return out


def _yes(v: Any) -> bool | None:
    s = _norm(v)
    if s in ("yes", "sim", "ναι", "true", "1"):
        return True
    if s in ("no", "não", "όχι", "false", "0"):
        return False
    return None


@dataclass
class Mapped:
    submission_id: str
    lat: float
    lon: float
    observed_at: datetime
    observation_kind: str | None        # "report", "instream_look", or None (no evidence)
    positive: bool
    features: tuple[tuple[str, bool], ...]
    reason: str

    def to_observation(self, node_id: str) -> Observation | None:
        if self.observation_kind is None:
            return None
        return Observation(self.observation_kind, self.positive, node_id=node_id, role="citizen",
                           features=self.features, observed_at=self.observed_at,
                           observer=f"oah:{self.submission_id}")


def map_submission(sub: dict[str, Any]) -> Mapped:
    """Map one OAH submission dict. Required: id, latitude, longitude. Optional: created_at and the answers."""
    try:
        sid, lat, lon = str(sub["id"]), float(sub["latitude"]), float(sub["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"submission needs id, latitude and longitude: {exc}") from exc
    when = sub.get("created_at")
    observed = datetime.fromisoformat(when) if when else datetime.now(timezone.utc)
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    flow = _choice(sub.get("water_flow"))
    aspect = _choice(sub.get("water_aspect"))
    pipes, sewage = _yes(sub.get("draining_pipes")), _yes(sub.get("sewage_discharge"))

    if "d" in flow or "dry (d)" in flow:
        return Mapped(sid, lat, lon, observed, None, False, (), "stream reported dry")
    feats: list[tuple[str, bool]] = []
    if "b" in aspect:
        feats.append(("brown_turbid", True))
    if "c" in aspect:
        feats.append(("foam", True))
    if pipes:
        feats.append(("pipe_flowing", True))
    polluted = bool(feats) or "d" in aspect or sewage is True
    if polluted:
        reasons = [r for r, on in (("turbid", "b" in aspect), ("foam", "c" in aspect), ("altered colour", "d" in aspect),
                                   ("polluted pipe", pipes), ("sewage discharge", sewage)) if on]
        return Mapped(sid, lat, lon, observed, "report", True, tuple(feats), ", ".join(reasons))
    if "a" in aspect and pipes is not True and sewage is not True:
        return Mapped(sid, lat, lon, observed, "instream_look", False, (), "clear water, no pipe or sewage")
    return Mapped(sid, lat, lon, observed, None, False, (), "no usable answer")

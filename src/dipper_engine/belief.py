"""Joint Bayesian belief over (hypothesis H, source S) for one pollution case on one reach.

State space: for each point-source hypothesis, one state per candidate outfall plus OUTSIDE
(upstream of the mapped reach or an unmapped entry); for each diffuse hypothesis, one state.
The table is small, so inference is exact and every update can be explained line by line.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from .graph import ReachGraph
from .model import (  # noqa: F401
    CHECK_TYPES, FEATURE_LABELS, HARMFUL, HYPOTHESES, HYPOTHESIS_LABELS, NONE, OUTSIDE, POINT_SOURCE,
    Context, ModelParams, activity, diffuse_presence, hypothesis_prior,
)

OBS_KINDS = ("report", *CHECK_TYPES.keys())


@dataclass(frozen=True)
class Observation:
    """One piece of evidence. A citizen `report` is a positive look-and-smell with features."""
    kind: str                                  # "report" or a CHECK_TYPES key
    positive: bool
    node_id: str | None = None                 # where (report / in-stream checks)
    candidate_id: str | None = None            # which outfall (outfall_look)
    role: str = "citizen"
    features: tuple[tuple[str, bool], ...] = ()  # (feature, present?) pairs
    observed_at: datetime | None = None
    observer: str | None = None                # pseudonymous id
    tier: str = "observed"                     # observed | simulated
    media: str | None = None                   # sha256 of a stored, redacted photo (for erasure requests)

    def __post_init__(self) -> None:
        if self.kind not in OBS_KINDS:
            raise ValueError(f"unknown observation kind {self.kind!r}")
        if self.kind == "outfall_look" and not self.candidate_id:
            raise ValueError("outfall_look needs candidate_id")
        if self.kind != "outfall_look" and not self.node_id:
            raise ValueError(f"{self.kind} needs node_id")
        if self.observed_at is not None and self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must include a time zone")

    def describe(self, graph: ReachGraph) -> str:
        where = graph.candidate(self.candidate_id).label if self.candidate_id else graph.node_label(self.node_id)
        verb = {"report": "Report", "instream_look": "Look and smell", "outfall_look": "Outfall look",
                "ammonium_strip": "Ammonium strip", "lab_ecoli": "Lab E. coli"}[self.kind]
        res = "positive" if self.positive else "clean"
        feats = [FEATURE_LABELS[f] for f, present in self.features if present]
        tail = f" ({', '.join(feats)})" if feats else ""
        return f"{verb} at {where}: {res}{tail} [{self.role}]"


@dataclass
class LedgerEntry:
    index: int
    text: str
    kind: str
    tier: str
    weight_bans: float                  # log10 likelihood ratio for `weight_for` vs the alternatives
    weight_for: str                     # hypothesis the evidence moved most ("" if no shift >= 0.2 bans)
    harm_bans: float                    # log10 likelihood ratio: harmful point-source pollution vs not
    entropy_before_bits: float
    entropy_after_bits: float
    p_harmful_before: float
    p_harmful_after: float
    top_source_after: tuple[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "top_source_after": list(self.top_source_after)}


class Belief:
    def __init__(self, graph: ReachGraph, ctx: Context, params: ModelParams | None = None,
                 candidate_weights: dict[str, float] | None = None) -> None:
        self.graph, self.ctx = graph, ctx
        self.params = params or ModelParams()
        self.states: list[tuple[str, str]] = []
        for h in HYPOTHESES:
            if h in POINT_SOURCE:
                self.states += [(h, c.id) for c in graph.candidates] + [(h, OUTSIDE)]
            else:
                self.states.append((h, NONE))
        self.h_of = np.array([HYPOTHESES.index(h) for h, _ in self.states])
        self.s_of = [s for _, s in self.states]
        self._point = np.array([h in POINT_SOURCE for h, _ in self.states])
        self._harm = np.array([h in HARMFUL for h, _ in self.states])
        # Index of each state's entry point, for vectorised marginals over sources.
        self._s_keys = [c.id for c in graph.candidates] + [OUTSIDE, NONE]
        key_at = {k: i for i, k in enumerate(self._s_keys)}
        self._s_idx = np.array([key_at[s] for s in self.s_of])
        self._n_cand = len(graph.candidates)
        self._byh_cache: dict[int, np.ndarray] = {}
        self.logp = np.log(self._prior(candidate_weights))
        self.observations: list[Observation] = []
        self.ledger: list[LedgerEntry] = []
        self._pres_cache: dict[str, np.ndarray] = {}
        self.clock: datetime | None = None            # time of the latest observation
        self._positives: list[datetime] = []           # times of positive sightings (the start of a burst)
        self._persisting = False
        # Day/night discharge activity follows the stream's local time at each observation, not the case opening.
        tz = graph.meta.get("tz") if hasattr(graph, "meta") else None
        self._tz = ZoneInfo(tz) if tz else None
        self._act_ctx = ctx

    # ---- prior -----------------------------------------------------------------
    def _prior(self, weights: dict[str, float] | None) -> np.ndarray:
        ph = hypothesis_prior(self.params, self.ctx)
        w = {c.id: (weights or {}).get(c.id, c.prior_weight) for c in self.graph.candidates}
        wz = sum(w.values()) or 1.0
        out = np.zeros(len(self.states))
        for i, (h, s) in enumerate(self.states):
            if h in POINT_SOURCE:
                ps = self.params.prior_outside if s == OUTSIDE else (1 - self.params.prior_outside) * w[s] / wz
                if not self.graph.candidates:
                    ps = 1.0
                out[i] = ph[h] * ps
            else:
                out[i] = ph[h]
        return out / out.sum()

    # ---- helpers ---------------------------------------------------------------
    @property
    def p(self) -> np.ndarray:
        m = self.logp.max()
        e = np.exp(self.logp - m)
        return e / e.sum()

    def _by_h(self, table: dict[str, float]) -> np.ndarray:
        """A per-hypothesis table spread over states. Parameter tables never change, so this is cached."""
        v = self._byh_cache.get(id(table))
        if v is None:
            v = self._byh_cache[id(table)] = np.array([table.get(h, 0.0) for h, _ in self.states])
        return v

    def _activity_vec(self) -> np.ndarray:
        """P(discharging now) per state for point sources (0 for diffuse), cached with presence."""
        v = self._pres_cache.get("__activity__")
        if v is None:
            act = {h: self._activity(h) for h in POINT_SOURCE}
            v = self._pres_cache["__activity__"] = np.array([act.get(h, 0.0) for h, _ in self.states])
        return v

    def _activity(self, h: str) -> float:
        a = activity(self.params, h, self._act_ctx)
        return max(a, self.params.activity_persist) if self._persisting else a

    def at(self, t: datetime | None) -> None:
        """Set the discharge state (day or night, inside a burst or not) to what it was at time `t`. Evidence is
        scored at its own time, even when it arrives late (an offline report), and a recommendation at the time
        the check would be made."""
        if t is None:
            return
        if self._tz is not None:
            hour = t.astimezone(self._tz).hour
            if hour != self._act_ctx.hour:
                day_before = self._act_ctx.daytime
                self._act_ctx = replace(self._act_ctx, hour=hour)
                if self._act_ctx.daytime != day_before:
                    self._pres_cache.clear()
        window = self.params.persist_window_h * 3600
        on = any(0 <= (t - p).total_seconds() <= window for p in self._positives)
        if on != self._persisting:
            self._persisting = on
            self._pres_cache.clear()

    def _refresh_persistence(self) -> None:
        self.at(self.clock)

    def presence(self, node_id: str) -> np.ndarray:
        """P(pollution of the state's type is present at node_id at check time), per state."""
        if node_id in self._pres_cache:
            return self._pres_cache[node_id]
        up = self.graph.upstream_or_self(node_id)
        cand_node = {c.id: c.node_id for c in self.graph.candidates}
        out = np.zeros(len(self.states))
        for i, (h, s) in enumerate(self.states):
            if h in POINT_SOURCE:
                a = self._activity(h)
                if s == OUTSIDE:
                    out[i] = a * 0.9
                else:
                    out[i] = a if cand_node[s] in up else 0.0
            else:
                out[i] = diffuse_presence(self.params, h, self.ctx)
        self._pres_cache[node_id] = out
        return out

    def _feature_factor(self, obs: Observation, w_true: np.ndarray) -> np.ndarray:
        if not obs.features:
            return np.ones(len(self.states))
        trust = self.params.feature_trust[obs.role]
        f_true = np.ones(len(self.states))
        f_false = 1.0
        for f, present in obs.features:
            base = self.params.feature_base[f]
            pt = trust * self._by_h(self.params.feature_lik[f]) + (1 - trust) * base
            f_true *= pt if present else (1 - pt)
            f_false *= base if present else (1 - base)
        return w_true * f_true + (1 - w_true) * f_false

    # ---- likelihood --------------------------------------------------------------
    def likelihood(self, obs: Observation) -> np.ndarray:
        prm = self.params
        if obs.kind in ("report", "instream_look"):
            pres = self.presence(obs.node_id)
            det = prm.role_sensitivity[obs.role] * self._by_h(prm.visibility)
            fa = prm.role_false_alarm[obs.role]
            p_true = pres * det
            p_pos = p_true + (1 - p_true) * fa
            if not obs.positive:
                return 1 - p_pos
            return p_pos * self._feature_factor(obs, p_true / p_pos)
        if obs.kind == "outfall_look":
            act = self._activity_vec()
            at_src = (self._s_idx == self._s_keys.index(obs.candidate_id)).astype(float)
            det = prm.role_sensitivity[obs.role] * self._by_h(prm.visibility)
            fa = max(prm.role_false_alarm[obs.role], prm.other_outfall_dirty)
            p_true = at_src * act * det
            p_pos = p_true + (1 - p_true) * fa
            if not obs.positive:
                return 1 - p_pos
            return p_pos * self._feature_factor(obs, p_true / p_pos)
        if obs.kind == "ammonium_strip":
            pres = self.presence(obs.node_id)
            p_pos = pres * self._by_h(prm.ammonium_pos) + (1 - pres) * prm.ammonium_false_pos
            return p_pos if obs.positive else 1 - p_pos
        if obs.kind == "lab_ecoli":
            pres = self.presence(obs.node_id)
            p_pos = pres * self._by_h(prm.ecoli_pos) + (1 - pres) * prm.ecoli_false_pos
            return p_pos if obs.positive else 1 - p_pos
        raise ValueError(obs.kind)

    # ---- update ------------------------------------------------------------------
    def validate(self, obs: Observation) -> None:
        """Raise ValueError if the observation does not fit this reach. Nothing is changed."""
        if obs.candidate_id is not None and obs.candidate_id not in {c.id for c in self.graph.candidates}:
            raise ValueError(f"unknown outfall {obs.candidate_id}")
        if obs.node_id is not None and obs.node_id not in self.graph.nodes:
            raise ValueError(f"unknown stream point {obs.node_id}")
        if obs.role not in self.params.role_sensitivity:
            raise ValueError(f"unknown observer role {obs.role}")
        for f, _ in obs.features:
            if f not in self.params.feature_lik:
                raise ValueError(f"unknown feature {f}")

    def update(self, obs: Observation) -> LedgerEntry:
        """Bayes update. Validates first, so a rejected observation leaves the belief untouched."""
        self.validate(obs)
        # Score the observation with the discharge state at its own time: a check made hours after the last
        # positive sighting is outside that burst, and a late-arriving night-time report is scored as night.
        self.at(obs.observed_at or self.clock)
        text = obs.describe(self.graph)
        before = self.p
        lik = np.clip(self.likelihood(obs), 1e-12, None)
        if obs.kind == "report":
            lik = lik ** self._report_exponent(obs)
        lik = self._robust(lik, before)
        h_before, harm_before = self.location_entropy(before), float(before[self._harm].sum())
        hb, nb = before[self._harm].sum(), before[~self._harm].sum()
        harm_bans = math.log10(((before[self._harm] * lik[self._harm]).sum() / hb) /
                               ((before[~self._harm] * lik[~self._harm]).sum() / nb)) if hb > 0 and nb > 0 else 0.0
        # Evidence weight: the hypothesis whose odds moved most.
        best_h, best_w = HYPOTHESES[0], 0.0
        for k, h in enumerate(HYPOTHESES):
            m = self.h_of == k
            pin, pout = before[m].sum(), before[~m].sum()
            if pin <= 0 or pout <= 0:
                continue
            lr = ((before[m] * lik[m]).sum() / pin) / ((before[~m] * lik[~m]).sum() / pout)
            w = math.log10(lr)
            if abs(w) > abs(best_w):
                best_h, best_w = h, w
        self.logp = self.logp + np.log(lik)
        self.observations.append(obs)
        if obs.observed_at is not None:
            self.clock = max(self.clock, obs.observed_at) if self.clock else obs.observed_at
            if obs.positive and obs.kind in ("report", "instream_look", "outfall_look"):
                self._positives.append(obs.observed_at)
        self.at(self.clock)  # back to the latest time, which is where the next check starts from
        after = self.p
        entry = LedgerEntry(
            index=len(self.ledger) + 1, text=text, kind=obs.kind, tier=obs.tier,
            weight_bans=round(best_w, 3), weight_for=best_h if abs(best_w) >= 0.2 else "", harm_bans=round(harm_bans, 3),
            entropy_before_bits=round(h_before, 3), entropy_after_bits=round(self.location_entropy(after), 3),
            p_harmful_before=round(harm_before, 4), p_harmful_after=round(float(after[self._harm].sum()), 4),
            top_source_after=self.top_source(after),
        )
        self.ledger.append(entry)
        return entry

    def _report_exponent(self, obs: Observation) -> float:
        """Temper reports near earlier reports: neighbours often report the same event."""
        from .graph import haversine_m
        me = self.graph.nodes[obs.node_id]
        k = sum(1 for o in self.observations if o.kind == "report" and
                haversine_m(me.lat, me.lon, self.graph.nodes[o.node_id].lat, self.graph.nodes[o.node_id].lon)
                <= self.params.report_cluster_m)
        return 1.0 / (1.0 + self.params.report_temper * k)

    def _robust(self, lik: np.ndarray, p: np.ndarray) -> np.ndarray:
        eps = self.params.outlier_eps
        return (1 - eps) * lik + eps * float((p * lik).sum())

    def posterior_given(self, obs: Observation) -> tuple[np.ndarray, float]:
        """Posterior and predictive probability of `obs` without mutating the belief."""
        p = self.p
        lik = self._robust(self.likelihood(obs), p)
        z = float((p * lik).sum())
        return (p * lik) / max(z, 1e-300), z

    # ---- summaries ---------------------------------------------------------------
    def marginal_h(self, p: np.ndarray | None = None) -> dict[str, float]:
        p = self.p if p is None else p
        return {h: float(p[self.h_of == k].sum()) for k, h in enumerate(HYPOTHESES)}

    def marginal_s(self, p: np.ndarray | None = None) -> dict[str, float]:
        """P(entry point) for each candidate, OUTSIDE, and NONE (diffuse). Sums to 1."""
        return dict(zip(self._s_keys, self._marginal_s_vec(p).tolist()))

    def _marginal_s_vec(self, p: np.ndarray | None = None) -> np.ndarray:
        """Same as marginal_s, as an array in the order candidates, OUTSIDE, NONE."""
        p = self.p if p is None else p
        return np.bincount(self._s_idx, weights=p, minlength=len(self._s_keys))

    def entropy_s(self, p: np.ndarray | None = None) -> float:
        ms = self._marginal_s_vec(p)
        ms = ms[ms > 0]
        return float(-(ms * np.log2(ms)).sum())

    def location_entropy(self, p: np.ndarray | None = None) -> float:
        """Uncertainty (bits) about the entry point, given that there is a point source."""
        ms = self.marginal_s(p)
        pts = np.array([v for k, v in ms.items() if k != NONE])
        z = pts.sum()
        if z <= 0:
            return 0.0
        pts = pts[pts > 0] / z
        return float(-(pts * np.log2(pts)).sum())

    def top_source(self, p: np.ndarray | None = None) -> tuple[str, float]:
        ms = self._marginal_s_vec(p)
        if not self._n_cand:
            return (OUTSIDE, float(ms[-2]))
        i = int(np.argmax(ms[:self._n_cand]))  # first maximum, as max() over the dict did
        return (self._s_keys[i], round(float(ms[i]), 4))

    def p_harmful(self, p: np.ndarray | None = None) -> float:
        p = self.p if p is None else p
        return float(p[self._harm].sum())

    def p_polluted_at(self, node_id: str, p: np.ndarray | None = None, harmful_only: bool = True) -> float:
        p = self.p if p is None else p
        pres = self.presence(node_id)
        mask = self._harm if harmful_only else np.ones(len(self.states), bool)
        return float((p * pres)[mask].sum())

    def point_mass_upstream(self, node_id: str, p: np.ndarray | None = None) -> float:
        """Share of the point-source probability that lies upstream of (or at) node_id."""
        ms = self.marginal_s(p)
        total = sum(v for k, v in ms.items() if k != NONE)
        if total <= 0:
            return 0.0
        up = {c.id for c in self.graph.candidates_upstream_of(node_id)} | {OUTSIDE}
        return sum(ms[k] for k in up) / total

    def status(self) -> str:
        cid, pc = self.top_source()
        if cid not in (OUTSIDE, NONE) and pc >= self.params.localize_threshold:
            return "localized"
        benign_like = self.marginal_h()["benign"]
        if len(self.observations) >= self.params.min_checks_before_dismiss and benign_like >= self.params.dismiss_threshold:
            return "dismiss_proposed"
        return "open"

    def labels(self) -> dict[str, str]:
        return {**{c.id: c.label for c in self.graph.candidates}, OUTSIDE: "upstream or unmapped", NONE: "no single source"}

    def hypothesis_table(self) -> list[dict[str, Any]]:
        mh = self.marginal_h()
        return [{"id": h, "label": HYPOTHESIS_LABELS[h], "p": round(mh[h], 4), "harmful": h in HARMFUL}
                for h in sorted(HYPOTHESES, key=lambda x: -mh[x])]

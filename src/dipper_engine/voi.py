"""Next-best check: expected value of sample information (EVSI) plus search value, minus cost.

Score(k) = EVSI_advisory(k) + search_weight * ExpectedEntropyReduction_S(k) - cost(k) - delay(k)

EVSI is computed against the contact-advisory decision (issue / don't issue), so a check scores
high on that term only if its result could change what we would do. The search term rewards
narrowing down the entry point, which is what ends the case.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

from .belief import Belief, Observation
from .model import CHECK_TYPES, NONE, OUTSIDE, ModelParams


@dataclass(frozen=True)
class ProposedCheck:
    check_type: str
    role: str
    node_id: str | None = None
    candidate_id: str | None = None

    def as_observation(self, positive: bool) -> Observation:
        kind = self.check_type
        return Observation(kind=kind, positive=positive, node_id=self.node_id, candidate_id=self.candidate_id, role=self.role)

    def key(self) -> str:
        return f"{self.check_type}:{self.candidate_id or self.node_id}:{self.role}"


@dataclass
class Branch:
    probability: float
    p_harmful: float
    top_source: tuple[str, float]
    zone: str
    zone_mass: float
    advise: bool


@dataclass
class Recommendation:
    check: ProposedCheck
    label: str
    score: float
    evsi: float
    search_bits: float
    cost: float
    delay_h: float
    p_positive: float
    if_positive: Branch
    if_negative: Branch
    changes_decision: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items() if k not in ("check", "if_positive", "if_negative")}
        d["check"] = self.check.__dict__ | {"key": self.check.key()}
        d["if_positive"] = self.if_positive.__dict__ | {"top_source": list(self.if_positive.top_source)}
        d["if_negative"] = self.if_negative.__dict__ | {"top_source": list(self.if_negative.top_source)}
        return d


def advisory_losses(p_harm: float, stakes: float, params: ModelParams) -> tuple[float, float]:
    """(expected loss if we issue an advisory, expected loss if we don't)."""
    return (1 - p_harm) * params.loss_false_advisory, p_harm * params.loss_missed_advisory * stakes


def should_advise(p_harm: float, stakes: float, params: ModelParams) -> bool:
    issue, not_issue = advisory_losses(p_harm, stakes, params)
    return issue < not_issue


def zone_summary(belief: Belief, p: np.ndarray, cover: float = 0.8) -> tuple[str, float]:
    """Smallest set of entry points covering `cover` of the point-source mass, as a compact label."""
    ms = belief.marginal_s(p)
    point = {k: v for k, v in ms.items() if k != NONE}
    total = sum(point.values())
    if total <= 1e-9:
        return ("no single source", 0.0)
    order = sorted(point, key=lambda k: -point[k])
    chosen, acc = [], 0.0
    for k in order:
        chosen.append(k)
        acc += point[k] / total
        if acc >= cover:
            break
    idx = {c.id: i for i, c in enumerate(belief.graph.candidates)}
    labels = belief.labels()
    in_order = sorted([k for k in chosen if k in idx], key=idx.get)
    parts: list[str] = []
    run: list[str] = []
    for k in in_order:
        if run and idx[k] != idx[run[-1]] + 1:
            parts.append(_fmt_run(run, labels))
            run = []
        run.append(k)
    if run:
        parts.append(_fmt_run(run, labels))
    if OUTSIDE in chosen:
        parts.append(labels[OUTSIDE])
    return (", ".join(parts), acc)


def _fmt_run(run: list[str], labels: dict[str, str]) -> str:
    return labels[run[0]] if len(run) == 1 else f"{labels[run[0]]}…{labels[run[-1]]}"


def enumerate_checks(belief: Belief, roles: Iterable[str] = ("citizen", "trained", "inspector")) -> list[ProposedCheck]:
    roles = tuple(roles)
    out: list[ProposedCheck] = []

    def cheapest(ct: str) -> str | None:
        for r in ("citizen", "trained", "inspector"):
            if r in roles and r in CHECK_TYPES[ct].roles:
                return r
        return None

    for nid in belief.graph.access_nodes:
        for ct in ("instream_look", "ammonium_strip", "lab_ecoli"):
            r = cheapest(ct)
            if r:
                out.append(ProposedCheck(ct, r, node_id=nid))
    r = cheapest("outfall_look")
    if r:
        for c in belief.graph.candidates:
            if belief.graph.nodes[c.node_id].observable:
                out.append(ProposedCheck("outfall_look", r, candidate_id=c.id))
    return out


def evaluate(belief: Belief, check: ProposedCheck, stakes: float, explain: bool = True) -> Recommendation:
    """Score one check. With `explain=False` the plain-language parts (zones, label, reason) are skipped: the
    ranking only needs the numbers, and explanations are built for the few checks actually shown."""
    prm = belief.params
    ct = CHECK_TYPES[check.check_type]
    p_now = belief.p
    harm_now = belief.p_harmful(p_now)
    loss_now = min(advisory_losses(harm_now, stakes, prm))
    h_now = belief.entropy_s(p_now)

    branches: dict[bool, Branch] = {}
    exp_loss, exp_h = 0.0, 0.0
    for positive in (True, False):
        post, prob = belief.posterior_given(check.as_observation(positive))
        harm = belief.p_harmful(post)
        exp_loss += prob * min(advisory_losses(harm, stakes, prm))
        exp_h += prob * belief.entropy_s(post)
        zone, mass = zone_summary(belief, post) if explain else ("", 0.0)
        branches[positive] = Branch(probability=round(prob, 4), p_harmful=round(harm, 4),
                                    top_source=belief.top_source(post), zone=zone, zone_mass=round(mass, 3),
                                    advise=should_advise(harm, stakes, prm))
    evsi = max(0.0, loss_now - exp_loss)
    search = max(0.0, h_now - exp_h)
    score = evsi + prm.search_weight * search - ct.cost - prm.delay_penalty_per_day * ct.delay_h / 24
    changes = branches[True].advise != branches[False].advise
    if not explain:
        return Recommendation(check=check, label="", score=round(score, 5), evsi=round(evsi, 5), search_bits=round(search, 4),
                              cost=ct.cost, delay_h=ct.delay_h, p_positive=branches[True].probability,
                              if_positive=branches[True], if_negative=branches[False], changes_decision=changes, reason="")
    label = _check_label(belief, check)
    return Recommendation(check=check, label=label, score=round(score, 5), evsi=round(evsi, 5), search_bits=round(search, 4),
                          cost=ct.cost, delay_h=ct.delay_h, p_positive=branches[True].probability,
                          if_positive=branches[True], if_negative=branches[False], changes_decision=changes,
                          reason=_reason(belief, check, branches, changes))


def recommend(belief: Belief, stakes: float, k: int = 5, roles: Iterable[str] = ("citizen", "trained", "inspector"),
              exclude: set[str] | None = None, distinct: bool = False) -> list[Recommendation]:
    """Top-k checks by score. With `distinct`, a check whose outcomes are the same as a better-ranked check of
    the same type (for example the next access point along the same stretch) is left out, so a list shown to
    people offers real alternatives. The best check is always first either way."""
    fast = [evaluate(belief, c, stakes, explain=False) for c in enumerate_checks(belief, roles)
            if not exclude or c.key() not in exclude]
    fast.sort(key=lambda r: -r.score)  # stable: ties keep enumeration order, as before
    if not distinct:
        return [evaluate(belief, r.check, stakes) for r in fast[:k]]
    out, seen = [], set()
    for f in fast:
        r = evaluate(belief, f.check, stakes)
        sig = (r.check.check_type, r.check.role, r.if_positive.zone, r.if_negative.zone)
        if sig in seen:
            continue
        seen.add(sig)
        out.append(r)
        if len(out) == k:
            break
    return out


def _check_label(belief: Belief, check: ProposedCheck) -> str:
    ct = CHECK_TYPES[check.check_type]
    if check.candidate_id:
        return f"{ct.label}: {belief.graph.candidate(check.candidate_id).label}"
    return f"{ct.label} at {belief.graph.node_label(check.node_id)}"


def _reason(belief: Belief, check: ProposedCheck, br: dict[bool, Branch], changes: bool) -> str:
    pos, neg = br[True], br[False]
    tail = " The result could change the advisory decision." if changes else ""
    if check.check_type == "outfall_look":
        lab = belief.graph.candidate(check.candidate_id).label
        return (f"If {lab} is discharging, it becomes the likely source ({pos.top_source[1]:.0%}). "
                f"If it is not, the search continues in {neg.zone}.{tail}")
    if check.check_type == "lab_ecoli":
        return (f"Confirms or rules out faecal contamination here (result in about 24 h). "
                f"Chance of a positive result: {pos.probability:.0%}.{tail}")
    return (f"If this spot is clean, the source is most likely in {neg.zone} ({neg.zone_mass:.0%}). "
            f"If it is polluted, in {pos.zone} ({pos.zone_mass:.0%}).{tail}")

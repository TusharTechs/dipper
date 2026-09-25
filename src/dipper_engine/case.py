"""A pollution case: belief + context + lifecycle + a serialisable view for the API and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .belief import Belief, Observation
from .exposure import exposure_report, stakes
from .graph import ReachGraph
from .model import NONE, OUTSIDE, Context, ModelParams
from .voi import recommend, should_advise, zone_summary



@dataclass
class Action:
    type: str
    at: datetime
    approver: str | None
    payload: dict[str, Any] = field(default_factory=dict)


class Case:
    def __init__(self, case_id: str, graph: ReachGraph, ctx: Context, params: ModelParams | None = None,
                 opened_at: datetime | None = None) -> None:
        self.id = case_id
        self.graph = graph
        self.ctx = ctx
        self.belief = Belief(graph, ctx, params)
        self.stakes = stakes(graph)
        self.opened_at = opened_at or datetime.now(timezone.utc)
        self.actions: list[Action] = []
        self._status = "open"

    # ---- lifecycle ---------------------------------------------------------------
    def add(self, obs: Observation) -> None:
        self.belief.update(obs)
        if self._status == "open" and len(self.belief.observations) > 1:
            self._status = "localizing"

    def act(self, type_: str, approver: str | None, payload: dict[str, Any] | None = None) -> Action:
        """Human decisions. Advisories and utility handoffs require an approver."""
        if type_ in ("advisory", "notify_utility", "dismiss") and not approver:
            raise PermissionError(f"{type_} requires a human approver")
        a = Action(type=type_, at=datetime.now(timezone.utc), approver=approver, payload=payload or {})
        self.actions.append(a)
        self._status = {"notify_utility": "handed_off", "fixed": "fixed", "verified": "verified",
                        "close": "closed", "dismiss": "dismissed"}.get(type_, self._status)
        return a

    @property
    def status(self) -> str:
        if self._status in ("open", "localizing") and self.belief.status() == "localized":
            return "localized"
        return self._status

    # ---- explanations ------------------------------------------------------------
    def unknowns(self) -> list[str]:
        b = self.belief
        out = []
        mh = b.marginal_h()
        lead = max(mh, key=mh.get)
        cid, pc = b.top_source()
        if pc < b.params.localize_threshold:
            zone, mass = zone_summary(b, b.p)
            out.append(f"Which entry point: {mass:.0%} of the probability is spread over {zone}.")
        if lead == "foul":
            out.append("Whether the discharge is continuous (leaking sewer) or intermittent (misconnected appliance).")
        if mh[lead] < 0.7:
            out.append(f"What it is: the leading explanation has only {mh[lead]:.0%}.")
        if b.p_harmful() > 0.3 and not any(o.kind == "lab_ecoli" for o in b.observations):
            out.append("Pathogen presence and levels: not measured. A lab sample is needed to confirm.")
        if self.ctx.regime == "unknown":
            out.append("Recent rainfall: weather data unavailable.")
        for pl in exposure_report(b)[:1]:
            if 0.2 < pl["p_affected"] < 0.8:
                out.append(f"Whether it has reached {pl['label']} ({pl['p_affected']:.0%}).")
        return out

    # ---- view -------------------------------------------------------------------
    def _obs_view(self, o: Observation) -> dict[str, Any]:
        nid = self.graph.candidate(o.candidate_id).node_id if o.candidate_id else o.node_id
        nd = self.graph.nodes[nid]
        return {"kind": o.kind, "positive": o.positive, "role": o.role, "tier": o.tier, "lat": nd.lat, "lon": nd.lon,
                "where": self.graph.candidate(o.candidate_id).label if o.candidate_id else self.graph.node_label(o.node_id),
                "observed_at": o.observed_at.isoformat() if o.observed_at else None,
                "features": [f for f, present in o.features if present]}

    def view(self, n_recommendations: int = 5, roles: tuple[str, ...] = ("citizen", "trained", "inspector")) -> dict[str, Any]:
        b = self.belief
        labels = b.labels()
        ms = b.marginal_s()
        sources = []
        for c in self.graph.candidates:
            nd = self.graph.nodes[c.node_id]
            sources.append({"id": c.id, "label": c.label, "p": round(ms[c.id], 4), "lat": nd.lat, "lon": nd.lon,
                            "synthetic": c.synthetic, "observable": nd.observable})
        ribbon = [{"node_id": n.id, "lat": n.lat, "lon": n.lon, "p_polluted": round(b.p_polluted_at(n.id), 4)}
                  for n in self.graph.nodes.values()]
        p_harm = b.p_harmful()
        recs = recommend(b, self.stakes, k=n_recommendations, roles=roles)
        return {
            "id": self.id, "reach": self.graph.name, "city": self.graph.city, "status": self.status,
            "opened_at": self.opened_at.isoformat(),
            "context": {"regime": self.ctx.regime, "summary": self.ctx.describe(), "rain_48h_mm": self.ctx.rain_48h_mm,
                        "tmax_c": self.ctx.tmax_c, "dry_days": self.ctx.dry_days},
            "hypotheses": b.hypothesis_table(),
            "p_harmful": round(p_harm, 4),
            "advisory_suggested": should_advise(p_harm, self.stakes, b.params),
            "stakes": round(self.stakes, 3),
            "top_source": {"id": b.top_source()[0], "label": labels[b.top_source()[0]], "p": b.top_source()[1]},
            "outside_or_unmapped": round(ms[OUTSIDE], 4), "diffuse": round(ms[NONE], 4),
            "sources": sources, "ribbon": ribbon,
            "ledger": [e.as_dict() for e in b.ledger],
            "observations": [self._obs_view(o) for o in b.observations],
            "unknowns": self.unknowns(),
            "exposure": exposure_report(b),
            "recommendations": [r.as_dict() for r in recs],
            "actions": [{"type": a.type, "at": a.at.isoformat(), "approver": a.approver, "payload": a.payload} for a in self.actions],
            "model": {"version": "0.1.0", "note": "Likelihoods are literature and expert starting values; see docs/model-card.md."},
        }

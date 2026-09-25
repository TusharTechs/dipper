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
        if self.status in self.TERMINAL:
            raise ValueError(f"the case is {self.status}; open a new case for new evidence")
        self.belief.update(obs)
        if self._status == "open" and len(self.belief.observations) > 1:
            self._status = "localizing"

    # Allowed status for each action. Anything else is rejected, so a case cannot jump e.g. from open to verified.
    ALLOWED = {
        "dispatch": {"open", "localizing", "localized"}, "lab_request": {"open", "localizing", "localized", "handed_off"},
        "advisory": {"open", "localizing", "localized", "handed_off", "fixed"},
        "notify_utility": {"localized"}, "dismiss": {"open", "localizing", "localized"},
        "fixed": {"handed_off"}, "verified": {"fixed"}, "close": {"verified", "dismissed", "handed_off", "fixed"},
        "fhir_push": {"open", "localizing", "localized", "handed_off", "fixed", "verified", "closed", "dismissed"},
    }
    NEEDS_APPROVER = {"advisory", "notify_utility", "dismiss", "fixed", "verified", "close"}
    TERMINAL = {"closed", "dismissed", "verified"}

    def act(self, type_: str, approver: str | None, payload: dict[str, Any] | None = None,
            at: datetime | None = None) -> Action:
        """Human decisions, with an explicit transition table. Consequential actions require an approver."""
        if type_ not in self.ALLOWED:
            raise ValueError(f"unknown action {type_}")
        if type_ in self.NEEDS_APPROVER and not (approver and approver.strip()):
            raise PermissionError(f"{type_} requires a human approver")
        if self.status not in self.ALLOWED[type_]:
            raise ValueError(f"{type_.replace('_', ' ')} is not possible while the case is {self.status.replace('_', ' ')}")
        snapshot = {"status_before": self.status, "p_harmful": round(self.belief.p_harmful(), 4),
                    "top_source": list(self.belief.top_source()), "model_version": "0.2.0"}
        a = Action(type=type_, at=at or datetime.now(timezone.utc), approver=approver,
                   payload={**(payload or {}), "seen": (payload or {}).get("seen", snapshot)})
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

    def advisory_draft(self) -> dict[str, Any]:
        """Tiered wording for a public contact advisory. A person approves it; nothing here is a diagnosis."""
        b = self.belief
        reports = [o for o in b.observations if o.kind == "report" and o.role != "photo_model"]
        positives = [o for o in b.observations if o.kind != "report" and o.positive]
        cleans = [o for o in b.observations if not o.positive]
        feats = sorted({f for o in reports for f, present in o.features if present})
        lead = b.hypothesis_table()[0]
        cid, pc = b.top_source()
        labels = b.labels()
        places = [e["label"] for e in exposure_report(b) if e["p_affected"] >= 0.3][:3]
        from .model import FEATURE_LABELS
        observed = (f"{len(reports)} citizen report(s) of " + (", ".join(FEATURE_LABELS[f] for f in feats) or "pollution")
                    + f"; {len(positives)} positive and {len(cleans)} clean follow-up check(s).")
        inferred = (f"Model estimate, {lead['p']:.0%} likely: {lead['label'][0].lower() + lead['label'][1:]}. "
                    f"Most likely entry point: {labels[cid]} ({pc:.0%}).")
        risk = ("People and dogs in contact with the water downstream may be exposed to contamination"
                + (f", including near {', '.join(places)}." if places else "."))
        confirm = "Pathogens and their levels are not measured. A lab sample is needed to confirm."
        if any(o.kind == "lab_ecoli" and o.positive for o in b.observations):
            confirm = "A lab sample found faecal indicator bacteria above the screening threshold."
        reach = self.graph.name
        return {
            "tiers": {"observed": observed, "inferred": inferred, "possible_risk": risk, "needs_confirmation": confirm},
            "text": {
                "en": (f"Avoid contact with the water and keep dogs out of {reach} downstream of the affected stretch "
                       "until further notice. Reason: probable sewage discharge, not yet confirmed by a lab."),
                "pt": (f"Evite o contacto com a água e mantenha os cães fora da {reach}, a jusante do troço afetado, "
                       "até novo aviso. Motivo: provável descarga de esgoto, ainda sem confirmação laboratorial."),
            },
            "suggested": should_advise(b.p_harmful(), self.stakes, b.params),
        }

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
            "advisory_draft": self.advisory_draft(),
            "exposure": exposure_report(b),
            "recommendations": [r.as_dict() for r in recs],
            "actions": [{"type": a.type, "at": a.at.isoformat(), "approver": a.approver, "payload": a.payload} for a in self.actions],
            "model": {"version": "0.1.0", "note": "Likelihoods are literature and expert starting values; see docs/model-card.md."},
        }

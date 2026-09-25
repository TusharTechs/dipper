"""Export a case as a FHIR R4 Bundle built on the OneAquaHealth IG (hl7.eu.fhir.oah) plus Dipper response profiles.

OAH profiles used: LocationOah, GroupOah. Dipper profiles (fhir/ig): DipperCitizenObservation, DipperSourceCase
(DetectedIssue), DipperExposureRisk (RiskAssessment), DipperCheckRequest (ServiceRequest), DipperFieldTask (Task),
DipperSiteFlag (Flag), DipperAdvisory (Communication), DipperEngineProvenance (Provenance).

Synthetic content is tagged: meta.tag data tier and meta.security HL7 ActReason HTEST; ids are prefixed SIM-.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .belief import Observation
from .case import Case, advisory_text
from .model import HYPOTHESIS_LABELS, NONE, OUTSIDE
from .voi import recommend

OAH = "http://hl7.eu/fhir/ig/oah"
OAH_CS = f"{OAH}/CodeSystem/temporarySystem-oah-eu"
DIP = "https://example.org/fhir/dipper"
DIP_CS = f"{DIP}/CodeSystem/dipper-codes"
SCT = "http://snomed.info/sct"
BASE = "https://example.org/fhir/dipper-demo"
IDS = "urn:dipper"   # identifier namespaces (example.org is not allowed for identifier systems)
from . import __version__ as ENGINE_VERSION

FEATURE_CODES = {
    "grey": (DIP_CS, "grey-discolouration", "Grey or milky water"),
    "sewage_odour": (DIP_CS, "sewage-odour", "Sewage smell"),
    "pipe_flowing": (DIP_CS, "pipe-dry-weather-flow", "Pipe discharging"),
    "sewage_fungus": (DIP_CS, "sewage-fungus", "Sewage fungus growth"),
    "brown_turbid": (DIP_CS, "brown-turbid", "Brown, muddy water"),
    "green": (DIP_CS, "green-water", "Green water or scum"),
    "dead_fish": (DIP_CS, "dead-fish", "Dead fish"),
    "foam": (DIP_CS, "foam", "Foam"),
}
CHECK_CODES = {
    "report": ("pollution-sighting", "Pollution sighting"),
    "instream_look": ("instream-look", "Look and smell at the stream"),
    "outfall_look": ("outfall-look", "Look and smell at an outfall"),
    "ammonium_strip": ("ammonium-strip", "Ammonium test strip"),
    "lab_ecoli": ("lab-ecoli", "Laboratory E. coli sample"),
}


def _narrative(res: dict[str, Any]) -> str:
    """Minimal human-readable narrative (dom-6)."""
    from html import escape
    rt = res["resourceType"]
    bits = [res.get("name"), (res.get("code") or {}).get("text") or next(iter((res.get("code") or {}).get("coding", [])), {}).get("display"),
            res.get("detail"), res.get("description"), res.get("status")]
    if rt == "RiskAssessment":
        bits.append(res["prediction"][0]["rationale"])
    text = " · ".join(escape(str(b)) for b in bits if b)
    return f'<div xmlns="http://www.w3.org/1999/xhtml"><p><b>{rt}</b> {text}</p></div>'


def _staff_ref(approver: str | None) -> str:
    """'Rui Lopes (inspector, u_ab12) [demo]' -> 'inspector u_ab12': exports carry role and id, not names."""
    m = re.search(r"\(([^)]*)\)", approver or "")
    return m.group(1).replace(",", "") if m else "staff"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9.-]+", "-", s).strip("-")[:60]


def _coding(system: str, code: str, display: str) -> dict[str, str]:
    return {"system": system, "code": code, "display": display}


def _cc(system: str, code: str, display: str, text: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"coding": [_coding(system, code, display)]}
    if text:
        out["text"] = text
    return out


class _Builder:
    def __init__(self, case: Case, now: datetime) -> None:
        self.case, self.g, self.b = case, case.graph, case.belief
        self.now = now
        self.sim = any(o.tier == "simulated" for o in self.b.observations)
        self.pfx = "SIM-" if self.sim else ""
        self.entries: list[dict[str, Any]] = []
        self._locs: dict[str, str] = {}

    def meta(self, profile: str, tier: str | None = None) -> dict[str, Any]:
        m: dict[str, Any] = {"profile": [profile]}
        t = tier or ("simulated" if self.sim else "observed")
        m["tag"] = [_coding(DIP_CS, t, t.capitalize())]
        if t == "simulated" or self.sim:
            m["security"] = [_coding("http://terminology.hl7.org/CodeSystem/v3-ActReason", "HTEST", "test health data")]
        return m

    def add(self, res: dict[str, Any]) -> str:
        ref = f"{res['resourceType']}/{res['id']}"
        if "text" not in res:
            res["text"] = {"status": "generated", "div": _narrative(res)}
        self.entries.append({"fullUrl": f"{BASE}/{ref}", "resource": res})
        return ref

    # ---- places ------------------------------------------------------------------
    def reach_location(self) -> str:
        if "reach" in self._locs:
            return self._locs["reach"]
        outlet = min(self.g.nodes.values(), key=lambda n: n.dist_to_outlet_m)
        ref = self.add({
            "resourceType": "Location", "id": f"{self.pfx}loc-reach-{_slug(self.g.name)}",
            "meta": self.meta(f"{OAH}/StructureDefinition/location-oah", "observed"),
            "identifier": [{"system": f"{IDS}:reach-id", "value": _slug(self.g.name).lower()}],
            "status": "active", "name": f"{self.g.name}, {self.g.city}", "mode": "instance",
            "description": "Stream reach built from OpenStreetMap (ODbL). Position is the reach outlet.",
            "type": [_cc(SCT, "420531007", "River")],
            "position": {"longitude": round(outlet.lon, 6), "latitude": round(outlet.lat, 6)},
        })
        self._locs["reach"] = ref
        return ref

    def point_location(self, node_id: str | None = None, candidate_id: str | None = None) -> str:
        key = f"c:{candidate_id}" if candidate_id else f"n:{node_id}"
        if key in self._locs:
            return self._locs[key]
        reach = self.reach_location()
        if candidate_id:
            c = self.g.candidate(candidate_id)
            nd = self.g.nodes[c.node_id]
            rid, name, tier = f"{self.pfx}loc-outfall-{c.id}", f"Candidate outfall {c.label}", "simulated" if c.synthetic else "observed"
            desc = "Candidate outfall" + (" (synthetic; placed for demonstration)" if c.synthetic else "")
        else:
            nd = self.g.nodes[node_id]
            rid, name, tier = f"{self.pfx}loc-pt-{_slug(node_id)}", self.g.node_label(node_id).capitalize(), "observed"
            desc = f"Stream point on {self.g.name}"
        ref = self.add({
            "resourceType": "Location", "id": rid, "meta": self.meta(f"{OAH}/StructureDefinition/location-oah", tier),
            "identifier": [{"system": f"{IDS}:point-id", "value": _slug(candidate_id or node_id)}],
            "status": "active", "name": name, "description": desc, "mode": "instance",
            "position": {"longitude": round(nd.lon, 6), "latitude": round(nd.lat, 6)},
            "partOf": {"reference": reach},
        })
        self._locs[key] = ref
        return ref

    # ---- evidence ------------------------------------------------------------------
    def observation(self, i: int, o: Observation) -> str:
        loc = self.point_location(o.node_id, o.candidate_id)
        code, disp = CHECK_CODES[o.kind]
        if o.kind in ("ammonium_strip", "lab_ecoli"):
            oah_code, oah_disp = ("ammonium", "Ammonium") if o.kind == "ammonium_strip" else ("coliforms", "Coliforms")
            main = {"coding": [_coding(OAH_CS, oah_code, oah_disp), _coding(DIP_CS, code, disp)]}
            value = {"valueCodeableConcept": _cc(DIP_CS, *(("above-threshold", "Above screening threshold") if o.positive
                                                           else ("below-threshold", "Below screening threshold")))}
        else:
            main = {"coding": [_coding(OAH_CS, "foam", "Foam/colour/smell"), _coding(DIP_CS, code, disp)]}
            value = {"valueBoolean": o.positive}
        res: dict[str, Any] = {
            "resourceType": "Observation", "id": f"{self.pfx}obs-{i:03d}",
            "meta": self.meta(f"{DIP}/StructureDefinition/dipper-citizen-observation", o.tier),
            "status": "final" if o.role == "inspector" else "preliminary",
            "category": [_cc("http://terminology.hl7.org/CodeSystem/observation-category", "survey" if o.role == "citizen" else "exam",
                             "Survey" if o.role == "citizen" else "Exam")],
            "code": main, "subject": {"reference": loc},
            "effectiveDateTime": (o.observed_at or self.now).isoformat(),
            "performer": [{"display": f"{o.role.capitalize()} ({o.observer or 'pseudonymous'})"}],
            **value,
        }
        comps = [{"code": _cc(*FEATURE_CODES[f]), "valueBoolean": present} for f, present in o.features]
        if comps:
            res["component"] = comps
        return self.add(res)

    def build(self) -> dict[str, Any]:
        b, case = self.b, self.case
        view = case.view(n_recommendations=1)
        obs_refs = [self.observation(i + 1, o) for i, o in enumerate(b.observations)]
        reach = self.reach_location()
        device = self.add({"resourceType": "Device", "id": f"{self.pfx}dev-dipper-engine",
                           "deviceName": [{"name": "Dipper engine", "type": "manufacturer-name"}],
                           "version": [{"value": ENGINE_VERSION}], "note": [{"text": "Parameters and their sources: docs/model-card.md"}]})
        top_id, top_p = b.top_source()
        top_label = b.labels()[top_id]
        lead = b.hypothesis_table()[0]
        implicated = [{"reference": reach}]
        if top_id not in (OUTSIDE, NONE):
            implicated.insert(0, {"reference": self.point_location(candidate_id=top_id)})
        issue = self.add({
            "resourceType": "DetectedIssue", "id": f"{self.pfx}case-{_slug(case.id)}",
            "meta": self.meta(f"{DIP}/StructureDefinition/dipper-source-case"),
            "identifier": [{"system": f"{IDS}:case-id", "value": case.id}],
            "status": "final" if case.status in ("handed_off", "fixed", "verified", "closed") else "preliminary",
            "code": _cc(DIP_CS, "suspected-point-source", "Suspected point-source pollution"),
            "severity": "high" if b.p_harmful() >= 0.8 else "moderate" if b.p_harmful() >= 0.4 else "low",
            "identifiedDateTime": case.opened_at.isoformat(), "implicated": implicated,
            "evidence": [{"detail": [{"reference": r} for r in obs_refs]}],
            "detail": (f"Leading explanation: {lead['label']} ({lead['p']:.0%}). Most likely entry point: {top_label} "
                       f"({top_p:.0%}). Case status: {case.status}. Model estimate from citizen and field evidence; "
                       f"pathogens not measured unless a lab result is listed."),
        })
        group = self.add({
            "resourceType": "Group", "id": f"{self.pfx}grp-reach-users-{_slug(self.g.name)}",
            "meta": self.meta(f"{OAH}/StructureDefinition/group-oah", "observed"),
            "type": "person", "actual": False, "name": f"People and animals using {self.g.name} downstream of the likely source",
            "characteristic": [{"code": _cc(DIP_CS, "reach-users", "People and animals using a stream reach"),
                                "valueReference": {"reference": reach}, "exclude": False}],
        })
        exposure = view["exposure"]
        p_exp = max([e["p_affected"] for e in exposure], default=b.p_harmful())
        places = "; ".join(f"{e['label']} ({e['p_affected']:.0%})" for e in exposure[:3]) or "no mapped contact places"
        risk = self.add({
            "resourceType": "RiskAssessment", "id": f"{self.pfx}risk-{_slug(case.id)}",
            "meta": self.meta(f"{DIP}/StructureDefinition/dipper-exposure-risk"),
            "status": "preliminary", "subject": {"reference": group}, "occurrenceDateTime": self.now.isoformat(),
            "performer": {"reference": device},
            "method": {"text": "Dipper Bayesian source search v" + ENGINE_VERSION},
            "basis": [{"reference": issue}] + [{"reference": r} for r in obs_refs],
            "prediction": [{
                "outcome": _cc(DIP_CS, "faecal-contact-exposure", "Contact with faecally contaminated water"),
                "probabilityDecimal": round(p_exp, 3),
                "qualitativeRisk": _cc("http://terminology.hl7.org/CodeSystem/risk-probability",
                                       *(("high", "High likelihood") if p_exp >= 0.6 else ("moderate", "Moderate likelihood") if p_exp >= 0.3 else ("low", "Low likelihood"))),
                "rationale": (f"{case.ctx.describe()}. {HYPOTHESIS_LABELS[lead['id']]} {lead['p']:.0%}; entry {top_label} {top_p:.0%}. "
                              f"Contact places downstream: {places}. Environmental exposure estimate only; no pathogen confirmed."),
            }],
        })
        targets = [issue, risk]
        recs = recommend(b, case.stakes, k=1)
        if recs and case.status in ("open", "localizing"):
            r = recs[0]
            ct_code, ct_disp = CHECK_CODES[r.check.check_type]
            loc = self.point_location(r.check.node_id, r.check.candidate_id)
            sr = self.add({
                "resourceType": "ServiceRequest", "id": f"{self.pfx}req-{_slug(case.id)}-next",
                "meta": self.meta(f"{DIP}/StructureDefinition/dipper-check-request"),
                "extension": [{"url": f"{DIP}/StructureDefinition/dipper-value-of-information", "valueDecimal": round(r.score, 4)},
                              {"url": f"{DIP}/StructureDefinition/dipper-check-cost", "valueDecimal": r.cost}],
                "status": "active", "intent": "proposal", "code": _cc(DIP_CS, ct_code, ct_disp, r.label),
                "subject": {"reference": loc}, "authoredOn": self.now.isoformat(), "requester": {"reference": device},
                "reasonCode": [{"text": r.reason}], "supportingInfo": [{"reference": issue}, {"reference": risk}],
            })
            self.add({
                "resourceType": "Task", "id": f"{self.pfx}task-{_slug(case.id)}-next",
                "meta": self.meta(f"{DIP}/StructureDefinition/dipper-field-task"),
                "status": "requested", "intent": "proposal", "basedOn": [{"reference": sr}], "for": {"reference": loc},
                "authoredOn": self.now.isoformat(), "businessStatus": {"text": f"Awaiting a {r.check.role} volunteer"},
                "description": r.label,
            })
            targets.append(sr)
        if case.status in ("localized", "handed_off") and top_id not in (OUTSIDE, NONE):
            # Localization is a probability (SourceBench: about 1 in 7 localizations is wrong), so the hand-off
            # asks the utility to confirm the entry point before anyone digs.
            loc = self.point_location(None, top_id)
            conf = self.add({
                "resourceType": "ServiceRequest", "id": f"{self.pfx}confirm-{_slug(case.id)}",
                "meta": self.meta(f"{DIP}/StructureDefinition/dipper-confirmation-request"),
                "status": "active", "intent": "order" if case.status == "handed_off" else "proposal",
                "code": _cc(DIP_CS, "confirm-entry", "Confirm the entry point before repair"),
                "subject": {"reference": loc}, "authoredOn": self.now.isoformat(), "requester": {"reference": device},
                "reasonCode": [{"text": f"{top_label} holds {top_p:.0%} of the probability; confirm with a dye test, "
                                        "smoke test or CCTV before repair."}],
                "supportingInfo": [{"reference": issue}, {"reference": risk}],
            })
            self.add({
                "resourceType": "Task", "id": f"{self.pfx}task-{_slug(case.id)}-confirm",
                "meta": self.meta(f"{DIP}/StructureDefinition/dipper-field-task"),
                "status": "requested", "intent": "order" if case.status == "handed_off" else "proposal",
                "basedOn": [{"reference": conf}], "for": {"reference": loc}, "authoredOn": self.now.isoformat(),
                "businessStatus": {"text": "Awaiting the utility"},
                "description": f"Confirm that {top_label} is the entry point (dye test, smoke test or CCTV) before repair.",
            })
            targets.append(conf)
        advisories = [a for a in case.actions if a.type == "advisory"]
        lifts = [a for a in case.actions if a.type == "lift_advisory"]
        if view["advisory_suggested"] or advisories:
            flag = self.add({
                "resourceType": "Flag", "id": f"{self.pfx}flag-{_slug(case.id)}",
                "meta": self.meta(f"{DIP}/StructureDefinition/dipper-site-flag"),
                "status": "active" if case.advisory_active or not advisories else "inactive",
                "code": _cc(DIP_CS, "contact-advisory", "Avoid contact with the water"),
                "subject": {"reference": reach}, "period": {"start": (advisories[0].at if advisories else self.now).isoformat()}
                | ({"end": lifts[-1].at.isoformat()} if advisories and not case.advisory_active and lifts else {}),
                "author": {"reference": device},
            })
            for k, a in enumerate(advisories):
                text = a.payload.get("text") or advisory_text(self.g.name, self.g.city)
                self.add({
                    "resourceType": "Communication", "id": f"{self.pfx}advisory-{_slug(case.id)}-{k + 1}",
                    "meta": self.meta(f"{DIP}/StructureDefinition/dipper-advisory"),
                    "status": "completed", "subject": {"reference": group}, "about": [{"reference": flag}, {"reference": risk}],
                    "sent": a.at.isoformat(), "sender": {"display": f"Approved by {_staff_ref(a.approver)}"},
                    # The wording the officer approved (kept with the approval): city language first, then English.
                    "payload": [{"contentString": text[l]} for l in sorted(text, key=lambda l: l == "en")],
                })
        self.add({
            "resourceType": "Provenance", "id": f"{self.pfx}prov-{_slug(case.id)}",
            "meta": self.meta(f"{DIP}/StructureDefinition/dipper-engine-provenance"),
            "target": [{"reference": t} for t in targets], "recorded": self.now.isoformat(),
            "agent": [{"type": _cc("http://terminology.hl7.org/CodeSystem/provenance-participant-type", "assembler", "Assembler"),
                       "who": {"reference": device}}],
            "entity": [{"role": "source", "what": {"reference": r}} for r in obs_refs],
        })
        return {
            "resourceType": "Bundle", "id": f"{self.pfx}bundle-{_slug(case.id)}",
            "meta": {"tag": [_coding(DIP_CS, "simulated" if self.sim else "observed", "Simulated" if self.sim else "Observed")]},
            "identifier": {"system": f"{IDS}:bundle-id", "value": f"{case.id}-{self.now:%Y%m%dT%H%M%S}"},
            "type": "collection", "timestamp": self.now.isoformat(), "entry": self.entries,
        }


def case_bundle(case: Case, now: datetime | None = None) -> dict[str, Any]:
    return _Builder(case, now or datetime.now(timezone.utc)).build()


def to_transaction(bundle: dict[str, Any]) -> dict[str, Any]:
    """Collection → transaction Bundle with idempotent PUTs, so re-sending a case updates rather than duplicates."""
    entries = []
    for e in bundle["entry"]:
        r = e["resource"]
        entries.append({"fullUrl": e["fullUrl"], "resource": r,
                        "request": {"method": "PUT", "url": f"{r['resourceType']}/{r['id']}"}})
    return {"resourceType": "Bundle", "type": "transaction", "meta": bundle.get("meta", {}),
            "identifier": bundle.get("identifier"), "entry": entries}


class FhirPushError(RuntimeError):
    pass


def push(bundle: dict[str, Any], base_url: str, token: str | None = None, timeout: float = 30.0) -> dict[str, Any]:
    """POST a transaction to a FHIR R4 server. Returns a summary of the server's transaction-response."""
    import httpx

    headers = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = httpx.post(base_url.rstrip("/"), json=to_transaction(bundle), headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise FhirPushError(f"FHIR server unreachable: {exc.__class__.__name__}") from exc
    if r.status_code >= 400:
        detail = ""
        try:
            issues = r.json().get("issue", [])
            detail = "; ".join(i.get("diagnostics", "") for i in issues[:3])
        except ValueError:
            pass
        raise FhirPushError(f"FHIR server returned {r.status_code}: {detail}"[:500])
    resp = r.json()
    statuses = [e.get("response", {}).get("status", "") for e in resp.get("entry", [])]
    return {"server": base_url, "resources": len(statuses),
            "created": sum(s.startswith("201") for s in statuses), "updated": sum(s.startswith("200") for s in statuses)}

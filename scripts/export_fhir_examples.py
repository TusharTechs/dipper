"""Export example FHIR Bundles from the C-014 replay (simulated evidence, tagged HTEST).

    uv run python scripts/export_fhir_examples.py      # writes fhir/examples/*.json
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from dipper_engine.fhir import case_bundle
from dipper_engine.scenario import replay

OUT = Path(__file__).resolve().parents[1] / "fhir" / "examples"
NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    case = None
    for ev in replay():
        case = ev["case"]
        if ev["step"] == 2:
            (OUT / "c014-searching.bundle.json").write_text(json.dumps(case_bundle(case, NOW), indent=2, ensure_ascii=False))
    case.act("advisory", approver="ph-officer-01")
    case.act("notify_utility", approver="tech-01", payload={"outfall": case.belief.top_source()[0]})
    (OUT / "c014-handed-off.bundle.json").write_text(json.dumps(case_bundle(case, NOW), indent=2, ensure_ascii=False))
    for p in sorted(OUT.glob("*.json")):
        b = json.loads(p.read_text())
        kinds: dict[str, int] = {}
        for e in b["entry"]:
            kinds[e["resource"]["resourceType"]] = kinds.get(e["resource"]["resourceType"], 0) + 1
        print(p.name, kinds)


if __name__ == "__main__":
    main()

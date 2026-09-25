"""SQLite event store. A case is persisted as its creation record plus an append-only list of events
(observations and human actions). Loading replays the events through the engine, so the stored
history doubles as an audit log and a case always reflects the current model version.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dipper_engine import Case, Context, Observation, ReachGraph

log = logging.getLogger("dipper")
SCHEMA_VERSION = 2

SCHEMA = """
create table if not exists cases (
  id text primary key, reach_id text not null, opened_at text not null,
  context text not null, scenario_truth text
);
create table if not exists events (
  case_id text not null references cases(id), seq integer not null, at text not null,
  type text not null check (type in ('observation', 'action')), payload text not null,
  primary key (case_id, seq)
);
"""


def obs_to_dict(o: Observation) -> dict[str, Any]:
    d = asdict(o)
    d["features"] = [list(f) for f in o.features]
    d["observed_at"] = o.observed_at.isoformat() if o.observed_at else None
    return d


def obs_from_dict(d: dict[str, Any]) -> Observation:
    d = {"media": None, **d}
    return Observation(**{**d, "features": tuple(tuple(f) for f in d["features"]),
                          "observed_at": datetime.fromisoformat(d["observed_at"]) if d["observed_at"] else None})


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by all threads; callers serialise access with the API's lock.
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("pragma journal_mode=wal")
        self.db.execute("pragma foreign_keys=on")
        self.db.executescript(SCHEMA)
        version = self.db.execute("pragma user_version").fetchone()[0]
        if version < SCHEMA_VERSION:  # v1 → v2 needs no data change; bump the marker for future migrations
            self.db.execute(f"pragma user_version = {SCHEMA_VERSION}")
            self.db.commit()

    def create(self, case: Case, reach_id: str, scenario_truth: str | None = None) -> None:
        with self.db:
            self.db.execute("insert into cases values (?, ?, ?, ?, ?)",
                            (case.id, reach_id, case.opened_at.isoformat(), json.dumps(asdict(case.ctx)), scenario_truth))
            for o in case.belief.observations:
                self._append(case.id, "observation", obs_to_dict(o))

    def add_observation(self, case_id: str, obs: Observation) -> None:
        with self.db:
            self._append(case_id, "observation", obs_to_dict(obs))

    def add_action(self, case_id: str, type_: str, approver: str | None, payload: dict[str, Any], at: datetime) -> None:
        with self.db:
            self._append(case_id, "action", {"type": type_, "approver": approver, "payload": payload, "at": at.isoformat()})

    def _append(self, case_id: str, type_: str, payload: dict[str, Any]) -> None:
        seq = self.db.execute("select coalesce(max(seq), 0) + 1 from events where case_id = ?", (case_id,)).fetchone()[0]
        at = datetime.now(timezone.utc).isoformat()
        self.db.execute("insert into events values (?, ?, ?, ?, ?)", (case_id, seq, at, type_, json.dumps(payload)))

    def load_all(self, reach_loader) -> tuple[dict[str, Case], dict[str, str], dict[str, str]]:
        """Rebuild every case. A case that fails to replay is skipped and logged, never fatal."""
        cases, reach_of, truth = {}, {}, {}
        rows = self.db.execute("select * from cases").fetchall()
        for cid, reach_id, opened_at, ctx, tr in sorted(rows, key=lambda r: datetime.fromisoformat(r[2])):
            try:
                graph: ReachGraph = reach_loader(reach_id)
                case = Case(cid, graph, Context(**json.loads(ctx)), opened_at=datetime.fromisoformat(opened_at))
                for type_, payload in self.db.execute(
                        "select type, payload from events where case_id = ? order by seq", (cid,)):
                    p = json.loads(payload)
                    if type_ == "observation":
                        case.add(obs_from_dict(p))
                    else:
                        case.act(p["type"], p["approver"], p["payload"], at=datetime.fromisoformat(p["at"]), replay=True)
            except Exception as exc:  # noqa: BLE001 - one bad case must not stop the service
                log.error(json.dumps({"event": "case_quarantined", "case": cid, "error": str(exc)[:200]}))
                continue
            cases[cid], reach_of[cid] = case, reach_id
            if tr:
                truth[cid] = tr
        return cases, reach_of, truth

    def next_number(self) -> int:
        rows = self.db.execute("select id from cases where id like 'C-%'").fetchall()
        nums = [int(r[0][2:]) for r in rows if r[0][2:].isdigit()]
        return max(nums, default=0) + 1

    def history(self, case_id: str) -> list[dict[str, Any]]:
        return [{"seq": s, "at": at, "type": t, "payload": json.loads(p)} for s, at, t, p in
                self.db.execute("select seq, at, type, payload from events where case_id = ? order by seq", (case_id,))]

"""SourceBench: compare search strategies for locating a pollution source. SIMULATION ONLY.

Each trial places a true foul-sewage source at a random candidate outfall, generates three
citizen reports downstream, then lets a strategy request checks until the engine localizes the
source (P >= threshold) or the budget runs out. Results are sampled from a "true world" that can
differ from the engine's model (`misspec`) and whose discharges come in bursts (a two-state Markov
process) that the engine does not model. Both make the benchmark harder than the engine's own
assumptions.

    uv run python -m dipper_engine.sim --trials 100 --seed 1
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import time
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .belief import Belief, Observation
from .exposure import stakes as reach_stakes
from .graph import ReachGraph, synthetic_tree
from .model import CHECK_TYPES, FEATURES, Context, ModelParams
from .voi import ProposedCheck, enumerate_checks, evaluate

Policy = Callable[[Belief, float, set[str], random.Random], ProposedCheck]


# ---- true world -------------------------------------------------------------------

@dataclass
class World:
    graph: ReachGraph
    source_id: str
    params: ModelParams
    h: str = "foul"
    p_stay: float = 0.8
    p_active: float = 0.6
    active: bool = True

    def step(self, rng: random.Random) -> None:
        if rng.random() > self.p_stay:
            self.active = rng.random() < self.p_active

    def sample(self, check: ProposedCheck, rng: random.Random) -> Observation:
        prm, h = self.params, self.h
        src_node = self.graph.candidate(self.source_id).node_id
        if check.check_type == "outfall_look":
            present = self.active and check.candidate_id == self.source_id
            det = prm.role_sensitivity[check.role] * prm.visibility[h]
            fa = max(prm.role_false_alarm[check.role], prm.other_outfall_dirty)
            p = det if present else fa
        else:
            present = self.active and src_node in self.graph.upstream_or_self(check.node_id)
            if check.check_type == "instream_look":
                det = prm.role_sensitivity[check.role] * prm.visibility[h]
                p = det + (1 - det) * prm.role_false_alarm[check.role] if present else prm.role_false_alarm[check.role]
            elif check.check_type == "ammonium_strip":
                p = prm.ammonium_pos[h] if present else prm.ammonium_false_pos
            else:
                p = prm.ecoli_pos[h] if present else prm.ecoli_false_pos
        return check.as_observation(rng.random() < p)

    def initial_reports(self, rng: random.Random, n: int = 3) -> list[Observation]:
        src_node = self.graph.candidate(self.source_id).node_id
        down = [x for x in self.graph.access_nodes if src_node in self.graph.upstream_or_self(x)]
        if not down:
            down = self.graph.downstream_path(src_node)
        reports = []
        for _ in range(n):
            feats = tuple((f, rng.random() < self.params.feature_lik[f][self.h]) for f in FEATURES)
            reports.append(Observation(kind="report", positive=True, node_id=rng.choice(down), role="citizen",
                                       features=feats, tier="simulated"))
        return reports


# ---- strategies -------------------------------------------------------------------

def policy_walk(b: Belief, s: float, done: set[str], rng: random.Random) -> ProposedCheck:
    """Classic bank walk: look at every outfall from the downstream end upwards."""
    for c in reversed(b.graph.candidates):
        pc = ProposedCheck("outfall_look", "citizen", candidate_id=c.id)
        if pc.key() not in done and b.graph.nodes[c.node_id].observable:
            return pc
    return policy_voi(b, s, done, rng)


def policy_bisect(b: Belief, s: float, done: set[str], rng: random.Random) -> ProposedCheck:
    """Look at the stream where the upstream probability mass is closest to half."""
    nid = min(b.graph.access_nodes, key=lambda x: abs(b.point_mass_upstream(x) - 0.5))
    return ProposedCheck("instream_look", "citizen", node_id=nid)


def policy_entropy(b: Belief, s: float, done: set[str], rng: random.Random) -> ProposedCheck:
    """Greedy information gain about the source, ignoring cost and the advisory decision."""
    return max(enumerate_checks(b), key=lambda c: evaluate(b, c, s).search_bits)


def policy_voi(b: Belief, s: float, done: set[str], rng: random.Random) -> ProposedCheck:
    """Dipper: EVSI + search value - cost - delay."""
    return max(enumerate_checks(b), key=lambda c: evaluate(b, c, s).score)


def policy_random(b: Belief, s: float, done: set[str], rng: random.Random) -> ProposedCheck:
    return rng.choice(enumerate_checks(b))


POLICIES: dict[str, Policy] = {"walk": policy_walk, "bisect": policy_bisect, "entropy": policy_entropy,
                               "voi": policy_voi, "random": policy_random}


# ---- runner -----------------------------------------------------------------------

@dataclass
class TrialResult:
    network: str
    policy: str
    checks: int
    cost: float
    localized: bool
    correct: bool
    p_true_final: float


def run_trial(graph: ReachGraph, policy: str, rng: random.Random, budget: int = 25, misspec: float = 1.0,
              bursty: bool = True, ctx: Context | None = None) -> TrialResult:
    ctx = ctx or Context(rain_48h_mm=0.0, tmax_c=26, hour=11, dry_days=7)
    model = ModelParams()
    world = World(graph, rng.choice(graph.candidates).id, model.perturbed(misspec) if misspec != 1.0 else model)
    if not bursty:
        world.p_stay = 0.0
    belief = Belief(graph, ctx, model)
    t = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
    for i, obs in enumerate(world.initial_reports(rng)):
        belief.update(dc_replace(obs, observed_at=t + timedelta(minutes=20 * i)))
    t += timedelta(minutes=60)
    s = reach_stakes(graph)
    done: set[str] = set()
    cost, n = 0.0, 0
    while belief.status() != "localized" and n < budget:
        check = POLICIES[policy](belief, s, done, rng)
        world.step(rng)
        belief.update(dc_replace(world.sample(check, rng), observed_at=t))
        t += timedelta(minutes=25)
        done.add(check.key())
        cost += CHECK_TYPES[check.check_type].cost
        n += 1
    top, _ = belief.top_source()
    return TrialResult(graph.name, policy, n, round(cost, 3), belief.status() == "localized", top == world.source_id,
                       round(belief.marginal_s()[world.source_id], 4))


def summarise(results: list[TrialResult]) -> list[dict]:
    rows = []
    keys = sorted({(r.network, r.policy) for r in results})
    for net, pol in keys + sorted({("ALL", r.policy) for r in results}):
        rs = [r for r in results if (net == "ALL" or r.network == net) and r.policy == pol]
        ok = [r for r in rs if r.localized and r.correct]
        rows.append({
            "network": net, "policy": pol, "trials": len(rs),
            "success_rate": round(len(ok) / len(rs), 3),
            "wrong_localization_rate": round(sum(r.localized and not r.correct for r in rs) / len(rs), 3),
            "median_checks": statistics.median(r.checks for r in rs),
            "median_checks_when_successful": statistics.median(r.checks for r in ok) if ok else None,
            "mean_cost": round(statistics.mean(r.cost for r in rs), 3),
        })
    return rows


def load_networks(reach_dir: Path, n_synthetic: int = 2, max_access: int = 60) -> list[ReachGraph]:
    """Synthetic trees plus cached real reaches (reaches with > max_access access points are skipped for speed)."""
    nets = []
    for i in range(n_synthetic):
        g = synthetic_tree(main_len_m=1800, n_branches=2, branch_len_m=500, seed=100 + i, name=f"synthetic-{i + 1}")
        g.place_synthetic_candidates(14, seed=100 + i)
        nets.append(g)
    for p in sorted(reach_dir.glob("*.geojson")):
        g = ReachGraph.from_geojson(json.loads(p.read_text()))
        if len(g.candidates) >= 4 and len(g.access_nodes) <= max_access:
            nets.append(g)
    return nets


def main() -> None:
    ap = argparse.ArgumentParser(description="SourceBench (simulation)")
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--policies", default="walk,bisect,entropy,voi,random")
    ap.add_argument("--misspec", type=float, default=1.3, help=">1 makes the true world noisier than the model")
    ap.add_argument("--no-bursty", action="store_true")
    ap.add_argument("--reaches", default=str(Path(__file__).resolve().parents[2] / "data" / "reaches"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "data" / "sourcebench" / "results.json"))
    args = ap.parse_args()
    nets = load_networks(Path(args.reaches))
    pols = args.policies.split(",")
    results: list[TrialResult] = []
    t0 = time.time()
    for net in nets:
        for k in range(args.trials):
            for pol in pols:
                rng = random.Random(f"{args.seed}-{net.name}-{k}")  # same truth for every policy
                results.append(run_trial(net, pol, rng, misspec=args.misspec, bursty=not args.no_bursty))
    rows = summarise(results)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[2]
    # Paths are stored relative to the repository, so results never carry a local home directory.
    rel = {k: (str(Path(v).resolve().relative_to(root)) if k in ("reaches", "out") and Path(v).resolve().is_relative_to(root)
               else Path(v).name if k in ("reaches", "out") else v) for k, v in vars(args).items()}
    out.write_text(json.dumps({"label": "SIMULATION", "args": rel, "networks": [n.name for n in nets],
                               "summary": rows, "elapsed_s": round(time.time() - t0, 1)}, indent=2))
    print(f"SourceBench (SIMULATION) · {len(nets)} networks · {args.trials} trials each · misspec={args.misspec} · "
          f"bursty={not args.no_bursty} · {time.time() - t0:.0f}s")
    print(f"{'network':28} {'policy':8} {'success':>8} {'wrong':>6} {'med.checks':>10} {'med.ok':>7} {'cost':>6}")
    for r in rows:
        print(f"{r['network'][:28]:28} {r['policy']:8} {r['success_rate']:8.0%} {r['wrong_localization_rate']:6.0%} "
              f"{r['median_checks']:10} {str(r['median_checks_when_successful']):>7} {r['mean_cost']:6.2f}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()

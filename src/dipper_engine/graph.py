"""Directed stream-network graph (edges point downstream) with candidate sources and places."""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

import networkx as nx

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


@dataclass
class Node:
    id: str
    lat: float
    lon: float
    dist_to_outlet_m: float = 0.0
    observable: bool = True
    access: bool = False


@dataclass
class Candidate:
    id: str
    node_id: str
    label: str
    prior_weight: float = 1.0
    synthetic: bool = True
    kind: str = "outfall"


@dataclass
class Place:
    """A place where people or animals may contact the water (playground, park, path, school)."""
    id: str
    kind: str
    label: str
    lat: float
    lon: float
    node_id: str
    weight: float = 1.0


@dataclass
class ReachGraph:
    name: str
    city: str
    nodes: dict[str, Node]
    g: nx.DiGraph
    candidates: list[Candidate] = field(default_factory=list)
    places: list[Place] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._reindex()

    # ---- topology -------------------------------------------------------------
    def _reindex(self) -> None:
        self._up: dict[str, frozenset[str]] = {
            n: frozenset(nx.ancestors(self.g, n)) | {n} for n in self.g.nodes
        }
        self._cand_by_id = {c.id: c for c in self.candidates}

    def upstream_or_self(self, node_id: str) -> frozenset[str]:
        return self._up[node_id]

    def node_label(self, node_id: str) -> str:
        """Human-readable location: access points are numbered P-1.. from upstream; distance to the outlet."""
        if not hasattr(self, "_access_label"):
            pos = {n: i for i, n in enumerate(self.branch_order())}
            acc = sorted((n for n in self.nodes.values() if n.access), key=lambda n: pos[n.id])
            self._access_label = {n.id: f"P-{i + 1}" for i, n in enumerate(acc)}
        km = self.nodes[node_id].dist_to_outlet_m / 1000
        tag = self._access_label.get(node_id)
        return f"point {tag} ({km:.1f} km above outlet)" if tag else f"{km:.2f} km above outlet"

    def candidate(self, cid: str) -> Candidate:
        return self._cand_by_id[cid]

    def candidates_upstream_of(self, node_id: str) -> list[Candidate]:
        up = self._up[node_id]
        return [c for c in self.candidates if c.node_id in up]

    def downstream_path(self, node_id: str) -> list[str]:
        path, cur, seen = [node_id], node_id, {node_id}
        while True:
            nxt = [v for v in self.g.successors(cur) if v not in seen]
            if not nxt:
                return path
            cur = nxt[0]
            seen.add(cur)
            path.append(cur)

    def along_distance_m(self, upstream: str, downstream: str) -> float | None:
        try:
            return nx.shortest_path_length(self.g, upstream, downstream, weight="length")
        except nx.NetworkXNoPath:
            return None

    def branch_order(self) -> list[str]:
        """Nodes ordered headwater-to-outlet with each branch contiguous (post-order DFS from the outlets,
        longest tributary first). Used to number candidates so labels read along the network."""
        rev = self.g.reverse(copy=False)
        up_len = {n: sum(self.g.edges[e]["length"] for e in self.g.subgraph(self._up[n]).edges) for n in self.g.nodes}
        order: list[str] = []
        seen: set[str] = set()
        sinks = sorted((n for n in self.g.nodes if self.g.out_degree(n) == 0), key=lambda n: -up_len[n])
        for sink in sinks:
            stack = [(sink, iter(sorted(rev.successors(sink), key=lambda c: -up_len[c])))]
            seen.add(sink)
            while stack:
                node, it = stack[-1]
                child = next((c for c in it if c not in seen), None)
                if child is None:
                    order.append(node)
                    stack.pop()
                else:
                    seen.add(child)
                    stack.append((child, iter(sorted(rev.successors(child), key=lambda c: -up_len[c]))))
        return order

    @property
    def total_length_m(self) -> float:
        return sum(d["length"] for _, _, d in self.g.edges(data=True))

    @property
    def access_nodes(self) -> list[str]:
        return [n.id for n in self.nodes.values() if n.access and n.observable]

    # ---- candidates and places --------------------------------------------------
    def set_candidates(self, cands: list[Candidate]) -> None:
        self.candidates = cands
        self._reindex()

    def place_synthetic_candidates(self, n: int, seed: int = 7, min_spacing_m: float = 40.0) -> list[Candidate]:
        """Place n synthetic outfalls on observable nodes, labelled O1..On from upstream to downstream."""
        rng = random.Random(seed)
        pool = [nd for nd in self.nodes.values() if nd.observable]
        rng.shuffle(pool)
        chosen: list[Node] = []
        for nd in pool:
            if all(haversine_m(nd.lat, nd.lon, c.lat, c.lon) >= min_spacing_m for c in chosen):
                chosen.append(nd)
            if len(chosen) == n:
                break
        pos = {n: i for i, n in enumerate(self.branch_order())}
        chosen.sort(key=lambda nd: pos[nd.id])
        cands = [Candidate(id=f"O{i + 1}", node_id=nd.id, label=f"O-{i + 1}") for i, nd in enumerate(chosen)]
        self.set_candidates(cands)
        return cands

    def attach_places(self, places: Iterable[dict[str, Any]], max_dist_m: float = 300.0) -> None:
        """Attach places to their nearest stream node. Weight decays with distance from the bank."""
        out = []
        for i, p in enumerate(places):
            nid, d = self.nearest_node(p["lat"], p["lon"])
            if d <= max_dist_m:
                w = p.get("weight", 1.0) * max(0.3, 1 - d / max_dist_m)
                out.append(Place(id=p.get("id", f"P{i + 1}"), kind=p["kind"], label=p.get("label", p["kind"]),
                                 lat=p["lat"], lon=p["lon"], node_id=nid, weight=round(w, 3)))
        self.places = out

    def nearest_node(self, lat: float, lon: float) -> tuple[str, float]:
        best, bd = "", float("inf")
        for nd in self.nodes.values():
            d = haversine_m(lat, lon, nd.lat, nd.lon)
            if d < bd:
                best, bd = nd.id, d
        return best, bd

    # ---- serialisation (GeoJSON FeatureCollection) --------------------------------
    def to_geojson(self) -> dict[str, Any]:
        feats: list[dict[str, Any]] = []
        for u, v, d in self.g.edges(data=True):
            a, b = self.nodes[u], self.nodes[v]
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[a.lon, a.lat], [b.lon, b.lat]]},
                          "properties": {"role": "edge", "from": u, "to": v, "length": round(d["length"], 2),
                                         "culvert": d.get("culvert", False), "unmapped": d.get("unmapped", False)}})
        for nd in self.nodes.values():
            props = {"role": "node", **{k: v for k, v in asdict(nd).items() if k not in ("lat", "lon")}}
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [nd.lon, nd.lat]}, "properties": props})
        for c in self.candidates:
            nd = self.nodes[c.node_id]
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [nd.lon, nd.lat]},
                          "properties": {"role": "candidate", **asdict(c)}})
        for p in self.places:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p.lon, p.lat]},
                          "properties": {"role": "place", **{k: v for k, v in asdict(p).items() if k not in ("lat", "lon")}}})
        return {"type": "FeatureCollection", "properties": {"name": self.name, "city": self.city, **self.meta}, "features": feats}

    @classmethod
    def from_geojson(cls, fc: dict[str, Any]) -> "ReachGraph":
        g = nx.DiGraph()
        nodes: dict[str, Node] = {}
        cands, places, edges = [], [], []
        for f in fc["features"]:
            p, (coords) = f["properties"], f["geometry"]["coordinates"]
            role = p["role"]
            if role == "node":
                nodes[p["id"]] = Node(id=p["id"], lat=coords[1], lon=coords[0], dist_to_outlet_m=p["dist_to_outlet_m"],
                                      observable=p["observable"], access=p["access"])
            elif role == "edge":
                edges.append((p["from"], p["to"], {"length": p["length"], "culvert": p["culvert"], "unmapped": p["unmapped"]}))
            elif role == "candidate":
                cands.append(Candidate(**{k: p[k] for k in ("id", "node_id", "label", "prior_weight", "synthetic", "kind")}))
            elif role == "place":
                places.append(Place(id=p["id"], kind=p["kind"], label=p["label"], lat=coords[1], lon=coords[0],
                                    node_id=p["node_id"], weight=p["weight"]))
        g.add_nodes_from(nodes)
        g.add_edges_from(edges)
        props = dict(fc.get("properties", {}))
        name, city = props.pop("name", "reach"), props.pop("city", "")
        return cls(name=name, city=city, nodes=nodes, g=g, candidates=cands, places=places, meta=props)


# ---- builders ------------------------------------------------------------------

def _finalise(name: str, city: str, g: nx.DiGraph, coords: dict[str, tuple[float, float]],
              access_spacing_m: float, meta: dict[str, Any]) -> ReachGraph:
    # Break any accidental cycles (bad OSM directions).
    while True:
        try:
            cyc = nx.find_cycle(g)
        except nx.NetworkXNoCycle:
            break
        g.remove_edge(*cyc[-1][:2])
    sinks = [n for n in g.nodes if g.out_degree(n) == 0]
    rev = g.reverse(copy=False)
    dist = nx.multi_source_dijkstra_path_length(rev, sinks, weight="length")
    nodes: dict[str, Node] = {}
    for n in g.nodes:
        inc = list(g.in_edges(n, data=True)) + list(g.out_edges(n, data=True))
        open_edge = any(not d.get("culvert") for *_, d in inc)
        lat, lon = coords[n]
        nodes[n] = Node(id=n, lat=lat, lon=lon, dist_to_outlet_m=float(dist.get(n, 0.0)), observable=open_edge or not inc)
    # Access points: observable nodes at least access_spacing_m apart, from upstream down.
    chosen: list[Node] = []
    for nd in sorted(nodes.values(), key=lambda x: -x.dist_to_outlet_m):
        if nd.observable and all(haversine_m(nd.lat, nd.lon, c.lat, c.lon) >= access_spacing_m for c in chosen):
            chosen.append(nd)
            nd.access = True
    return ReachGraph(name=name, city=city, nodes=nodes, g=g, meta=meta)


def from_osm(elements: list[dict[str, Any]], name: str, city: str, max_gap_m: float = 80.0,
             access_spacing_m: float = 100.0) -> ReachGraph:
    """Build a reach from Overpass JSON elements (ways with `(._;>;)` node recursion).

    OSM waterways are drawn in the direction of flow. Gaps between a way's end and another
    component (usually unmapped culverts) are bridged when shorter than `max_gap_m` and
    marked unobservable. The largest connected component is kept.
    """
    coords = {str(e["id"]): (e["lat"], e["lon"]) for e in elements if e["type"] == "node"}
    g = nx.DiGraph()
    for w in (e for e in elements if e["type"] == "way"):
        tags = w.get("tags", {})
        culvert = tags.get("tunnel") in ("culvert", "yes") or tags.get("covered") == "yes"
        ids = [str(i) for i in w["nodes"] if str(i) in coords]
        for a, b in zip(ids, ids[1:]):
            if a == b:
                continue
            length = haversine_m(*coords[a], *coords[b])
            g.add_edge(a, b, length=length, culvert=culvert, unmapped=False, osm_way=w["id"])
    joined = 0
    while True:
        comps = list(nx.weakly_connected_components(g))
        if len(comps) < 2:
            break
        comp_of = {n: i for i, c in enumerate(comps) for n in c}
        best: tuple[float, str, str] | None = None
        for sink in (n for n in g.nodes if g.out_degree(n) == 0):
            for n in g.nodes:
                if comp_of[n] == comp_of[sink]:
                    continue
                d = haversine_m(*coords[sink], *coords[n])
                if d <= max_gap_m and (best is None or d < best[0]):
                    best = (d, sink, n)
        if best is None:
            break
        d, a, b = best
        g.add_edge(a, b, length=d, culvert=True, unmapped=True)
        joined += 1
    comps = sorted(nx.weakly_connected_components(g),
                   key=lambda c: sum(g.edges[e]["length"] for e in g.subgraph(c).edges), reverse=True)
    dropped = len(comps) - 1
    g = g.subgraph(comps[0]).copy()
    return _finalise(name, city, g, coords, access_spacing_m,
                     {"source": "OpenStreetMap (ODbL)", "gaps_bridged": joined, "fragments_dropped": dropped})


def synthetic_tree(main_len_m: float = 2000.0, n_branches: int = 2, branch_len_m: float = 500.0,
                   spacing_m: float = 25.0, seed: int = 0, name: str = "synthetic", origin: tuple[float, float] = (40.20, -8.42),
                   access_spacing_m: float = 100.0) -> ReachGraph:
    """A simple main stem flowing south with tributaries joining from the east. For tests and SourceBench."""
    rng = random.Random(seed)
    lat0, lon0 = origin
    dlat = spacing_m / 111_320.0
    dlon = spacing_m / (111_320.0 * math.cos(math.radians(lat0)))
    g = nx.DiGraph()
    coords: dict[str, tuple[float, float]] = {}
    n_main = max(2, int(main_len_m / spacing_m))
    main = [f"m{i}" for i in range(n_main)]
    for i, nid in enumerate(main):
        coords[nid] = (lat0 - i * dlat, lon0 + rng.uniform(-0.2, 0.2) * dlon)
    for a, b in zip(main, main[1:]):
        g.add_edge(a, b, length=haversine_m(*coords[a], *coords[b]), culvert=False, unmapped=False)
    for k in range(n_branches):
        join = main[rng.randint(n_main // 5, n_main - 2)]
        n_br = max(2, int(branch_len_m / spacing_m))
        br = [f"b{k}_{i}" for i in range(n_br)]
        jl, jo = coords[join]
        for i, nid in enumerate(br):
            coords[nid] = (jl + (n_br - i) * dlat * 0.5, jo + (n_br - i) * dlon)
        for a, b in zip(br, br[1:] + [join]):
            g.add_edge(a, b, length=haversine_m(*coords[a], *coords[b]), culvert=False, unmapped=False)
    # One culverted stretch on the main stem.
    c0 = rng.randint(n_main // 3, n_main // 2)
    for a, b in zip(main[c0:c0 + 4], main[c0 + 1:c0 + 5]):
        g.edges[a, b]["culvert"] = True
    return _finalise(name, "synthetic", g, coords, access_spacing_m, {"source": "synthetic"})

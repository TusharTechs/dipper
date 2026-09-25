"""Observation model: hypotheses, priors, likelihood tables and check types.

Every number here is a starting value drawn from the literature and expert judgement,
not a local calibration. docs/model-card.md lists the source or rationale for each table.
Parameters live in a dataclass so the simulator can run with a deliberately
misspecified "true world" and test robustness.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

HYPOTHESES: tuple[str, ...] = ("foul", "overflow", "chemical", "sediment", "bloom", "benign")
HYPOTHESIS_LABELS = {
    "foul": "Foul sewage (misconnection or leaking sewer)",
    "overflow": "Wet-weather sewer overflow",
    "chemical": "Chemical or detergent discharge",
    "sediment": "Sediment runoff",
    "bloom": "Algal bloom",
    "benign": "Natural or benign (e.g. natural foam, iron bacteria)",
}
# Hypotheses with a locatable entry point on the network.
POINT_SOURCE = frozenset({"foul", "overflow", "chemical"})
# Hypotheses that would justify a contact advisory.
HARMFUL = frozenset({"foul", "overflow", "chemical"})

FEATURES: tuple[str, ...] = (
    "grey", "sewage_odour", "foam", "brown_turbid", "green", "pipe_flowing", "dead_fish", "sewage_fungus",
)
FEATURE_LABELS = {
    "grey": "grey or milky water",
    "sewage_odour": "sewage smell",
    "foam": "foam",
    "brown_turbid": "brown, muddy water",
    "green": "green water or scum",
    "pipe_flowing": "pipe discharging",
    "dead_fish": "dead fish",
    "sewage_fungus": "grey 'sewage fungus' growth",
}

ROLES: tuple[str, ...] = ("citizen", "trained", "inspector")

# OSM-free identifiers for the non-candidate source states.
OUTSIDE = "__outside__"   # point source upstream of the mapped reach or at an unmapped entry
NONE = "__diffuse__"      # hypothesis has no single entry point


@dataclass(frozen=True)
class CheckType:
    name: str
    label: str
    target: str            # "instream" (look at the stream at a node) or "outfall" (look at one outfall)
    cost: float            # normalised effort units (a citizen look ~0.05, a lab sample 0.5)
    delay_h: float         # hours until the result is available
    roles: tuple[str, ...]  # who can perform it


CHECK_TYPES: dict[str, CheckType] = {
    "instream_look": CheckType("instream_look", "Look and smell at the stream", "instream", 0.05, 0.0, ROLES),
    "outfall_look": CheckType("outfall_look", "Look and smell at an outfall", "outfall", 0.06, 0.0, ROLES),
    "ammonium_strip": CheckType("ammonium_strip", "Ammonium test strip", "instream", 0.12, 0.0, ("trained", "inspector")),
    "lab_ecoli": CheckType("lab_ecoli", "Lab E. coli sample", "instream", 0.50, 24.0, ("inspector",)),
}


def _d(**kw: float) -> dict[str, float]:
    return dict(kw)


@dataclass
class ModelParams:
    # Prior over hypotheses, by weather regime. "unknown" is used when weather is unavailable.
    prior_h: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "dry": _d(foul=0.35, overflow=0.03, chemical=0.12, sediment=0.08, bloom=0.12, benign=0.30),
        "wet": _d(foul=0.20, overflow=0.30, chemical=0.08, sediment=0.25, bloom=0.05, benign=0.12),
    })
    heat_bloom_boost: float = 2.0          # multiply bloom prior when dry and hot
    prior_outside: float = 0.10            # P(point source lies upstream / unmapped | point hypothesis)

    # Probability a point source is discharging at the time of a check.
    activity_day: dict[str, float] = field(default_factory=lambda: _d(foul=0.60, overflow=0.02, chemical=0.40))
    activity_night: dict[str, float] = field(default_factory=lambda: _d(foul=0.25, overflow=0.02, chemical=0.30))
    activity_wet_overflow: float = 0.90
    # Discharges come in bursts: within `persist_window_h` of a positive sighting, activity is at least this.
    activity_persist: float = 0.85
    persist_window_h: float = 2.0
    # Probability a diffuse phenomenon is visible at an arbitrary point of the reach.
    diffuse_presence_dry: dict[str, float] = field(default_factory=lambda: _d(sediment=0.30, bloom=0.80, benign=0.35))
    diffuse_presence_wet: dict[str, float] = field(default_factory=lambda: _d(sediment=0.90, bloom=0.60, benign=0.35))

    # How visible each kind of pollution is to a person looking and smelling.
    visibility: dict[str, float] = field(default_factory=lambda: _d(
        foul=0.90, overflow=0.90, chemical=0.80, sediment=0.95, bloom=0.90, benign=0.70))
    # Observer sensitivity / false-alarm rate for look-and-smell checks, by role.
    # photo_model = features read from a citizen photo by a multimodal model: deliberately weaker than any person.
    role_sensitivity: dict[str, float] = field(default_factory=lambda: _d(citizen=0.80, trained=0.90, inspector=0.95, photo_model=0.60))
    role_false_alarm: dict[str, float] = field(default_factory=lambda: _d(citizen=0.10, trained=0.06, inspector=0.03, photo_model=0.15))
    # Rate at which some *other* outfall looks polluted (background dirty outfalls).
    other_outfall_dirty: float = 0.06

    # P(feature reported | pollution truly seen, hypothesis). Features are treated as conditionally independent.
    feature_lik: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "grey":          _d(foul=0.70, overflow=0.50, chemical=0.30, sediment=0.10, bloom=0.05, benign=0.10),
        "sewage_odour":  _d(foul=0.75, overflow=0.60, chemical=0.15, sediment=0.05, bloom=0.15, benign=0.05),
        "foam":          _d(foul=0.30, overflow=0.30, chemical=0.50, sediment=0.10, bloom=0.20, benign=0.40),
        "brown_turbid":  _d(foul=0.20, overflow=0.60, chemical=0.20, sediment=0.90, bloom=0.10, benign=0.20),
        "green":         _d(foul=0.05, overflow=0.05, chemical=0.10, sediment=0.05, bloom=0.85, benign=0.10),
        "pipe_flowing":  _d(foul=0.60, overflow=0.70, chemical=0.50, sediment=0.30, bloom=0.02, benign=0.10),
        "dead_fish":     _d(foul=0.10, overflow=0.15, chemical=0.30, sediment=0.05, bloom=0.20, benign=0.01),
        "sewage_fungus": _d(foul=0.40, overflow=0.20, chemical=0.05, sediment=0.01, bloom=0.02, benign=0.02),
    })
    # Feature rates in false-alarm reports (someone reports pollution that is not there).
    feature_base: dict[str, float] = field(default_factory=lambda: _d(
        grey=0.15, sewage_odour=0.10, foam=0.25, brown_turbid=0.30, green=0.15,
        pipe_flowing=0.20, dead_fish=0.03, sewage_fungus=0.03))
    # How much a role's feature answers are trusted (1 = take at face value, 0 = ignore).
    feature_trust: dict[str, float] = field(default_factory=lambda: _d(citizen=0.7, trained=0.85, inspector=0.95, photo_model=0.4))

    # Measured checks: P(positive | pollution present at the point, hypothesis) and P(positive | absent).
    ammonium_pos: dict[str, float] = field(default_factory=lambda: _d(
        foul=0.85, overflow=0.75, chemical=0.25, sediment=0.15, bloom=0.10, benign=0.05))
    ammonium_false_pos: float = 0.08
    ecoli_pos: dict[str, float] = field(default_factory=lambda: _d(
        foul=0.95, overflow=0.95, chemical=0.10, sediment=0.45, bloom=0.10, benign=0.10))
    ecoli_false_pos: float = 0.05

    # Decision model for the contact-advisory decision.
    loss_false_advisory: float = 1.0
    loss_missed_advisory: float = 4.0      # multiplied by the exposure index (0..1)
    search_weight: float = 1.20            # value per bit of source-location entropy removed
    # Correlated reports: the k-th report within `report_cluster_m` of earlier ones enters with exponent 1/(1+0.5k).
    report_cluster_m: float = 150.0
    report_temper: float = 0.5
    # Robustness: with probability `outlier_eps` an observation is treated as uninformative (model may be wrong).
    outlier_eps: float = 0.08
    delay_penalty_per_day: float = 0.10

    # Stopping rules (a person still decides).
    localize_threshold: float = 0.85
    dismiss_threshold: float = 0.90
    min_checks_before_dismiss: int = 3

    def perturbed(self, factor: float) -> "ModelParams":
        """A misspecified copy: detection rates scaled down, false alarms scaled up by `factor`."""
        def scale(d: dict[str, float], f: float) -> dict[str, float]:
            return {k: min(0.99, max(0.01, v * f)) for k, v in d.items()}
        return replace(
            self,
            role_sensitivity=scale(self.role_sensitivity, 1 / factor),
            role_false_alarm=scale(self.role_false_alarm, factor),
            activity_day=scale(self.activity_day, 1 / factor),
            ammonium_pos=scale(self.ammonium_pos, 1 / factor),
            ammonium_false_pos=min(0.99, self.ammonium_false_pos * factor),
        )


@dataclass(frozen=True)
class Context:
    """Environmental context at the time of the case."""
    rain_48h_mm: float | None = None
    tmax_c: float | None = None
    hour: int = 12
    dry_days: int | None = None

    @property
    def regime(self) -> str:
        if self.rain_48h_mm is None:
            return "unknown"
        return "wet" if self.rain_48h_mm >= 5.0 else "dry"

    @property
    def daytime(self) -> bool:
        return 7 <= self.hour <= 22

    def describe(self) -> str:
        if self.rain_48h_mm is None:
            return "Weather unknown: priors widened."
        parts = [f"{self.rain_48h_mm:.1f} mm rain in 48 h"]
        if self.dry_days is not None and self.regime == "dry":
            parts.append(f"{self.dry_days} dry days")
        if self.tmax_c is not None:
            parts.append(f"max {self.tmax_c:.0f} °C")
        return ", ".join(parts)


def hypothesis_prior(params: ModelParams, ctx: Context) -> dict[str, float]:
    if ctx.regime == "unknown":
        prior = {h: 0.5 * params.prior_h["dry"][h] + 0.5 * params.prior_h["wet"][h] for h in HYPOTHESES}
    else:
        prior = dict(params.prior_h[ctx.regime])
    if ctx.regime == "dry" and ctx.tmax_c is not None and ctx.tmax_c >= 28:
        prior["bloom"] *= params.heat_bloom_boost
    z = sum(prior.values())
    return {h: prior[h] / z for h in HYPOTHESES}


def activity(params: ModelParams, h: str, ctx: Context) -> float:
    """P(point source of type h is discharging at the check time)."""
    if h == "overflow" and ctx.regime == "wet":
        return params.activity_wet_overflow
    if h == "overflow" and ctx.regime == "unknown":
        return 0.5 * (params.activity_wet_overflow + params.activity_day["overflow"])
    table = params.activity_day if ctx.daytime else params.activity_night
    return table[h]


def diffuse_presence(params: ModelParams, h: str, ctx: Context) -> float:
    if ctx.regime == "wet":
        return params.diffuse_presence_wet[h]
    if ctx.regime == "dry":
        return params.diffuse_presence_dry[h]
    return 0.5 * (params.diffuse_presence_wet[h] + params.diffuse_presence_dry[h])

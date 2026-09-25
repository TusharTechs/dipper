"""Dipper engine: Bayesian source hunting for pollution in urban streams."""

__version__ = "0.3.0"  # defined first: submodules record it in audit snapshots and FHIR provenance

from .belief import Belief, Observation  # noqa: E402
from .case import Case  # noqa: E402
from .graph import ReachGraph, from_osm, synthetic_tree  # noqa: E402
from .model import Context, ModelParams  # noqa: E402
from .voi import recommend  # noqa: E402

__all__ = ["Belief", "Case", "Context", "ModelParams", "Observation", "ReachGraph", "from_osm", "recommend", "synthetic_tree"]

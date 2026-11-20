"""fttxplan: open-source FTTx / GPON network planning in Python.

Route fibre along real roads, place splitters, size cables, check the optical budget
and get a bill of materials, from three inputs: roads, an OLT site and premises.

>>> import fttxplan
>>> roads, homes, olt = fttxplan.synthetic_town(blocks=2)
>>> design = fttxplan.plan(roads, olt, homes, crs=roads.crs, split_levels="1:32")
>>> design.summary()["premises"]
120
"""

from .config import CABLE_SIZES, PON_CLASSES, SPLITTER_LOSS_DB, DesignConfig, parse_split
from .datasets import load_demo, synthetic_town
from .design import Design, plan
from .network import RoadNetwork

__version__ = "0.1.0"

__all__ = [
    "CABLE_SIZES",
    "PON_CLASSES",
    "SPLITTER_LOSS_DB",
    "Design",
    "DesignConfig",
    "RoadNetwork",
    "load_demo",
    "parse_split",
    "plan",
    "synthetic_town",
    "__version__",
]

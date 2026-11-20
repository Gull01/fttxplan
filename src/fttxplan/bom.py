"""Bill of materials."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    from .design import Design


def build_bom(design: Design, unit_costs: dict[str, float] | None = None) -> pd.DataFrame:
    """Return the bill of materials as a table with ``category, item, quantity, unit``.

    Cable quantities include ``slack_ratio``. If ``unit_costs`` maps item names (as they appear
    in the ``item`` column) to a price per unit, ``unit_cost`` and ``cost`` columns are added.
    """
    cfg = design.config
    slack = 1 + cfg.slack_ratio
    rows: list[dict] = []

    def add(category, item, qty, unit):
        if qty:
            rows.append({"category": category, "item": item, "quantity": qty, "unit": unit})

    cables = design.cables
    for tier, label in (("feeder", "Feeder cable"), ("distribution", "Distribution cable")):
        sub = cables[cables.tier == tier]
        for size, grp in sub.groupby("cable_size"):
            metres = float((grp.length_m * grp.n_cables).sum()) * slack
            add("Cable", f"{label} {int(size)}F", round(metres), "m")
    add("Cable", "Drop cable 1F", round(float(design.premises.drop_total_m.sum()) * slack), "m")

    sp = design.splitters
    for (level, ratio), grp in sp.groupby(["level", "ratio"]):
        add("Passive", f"PLC splitter 1:{ratio} (level {level + 1})", len(grp), "pcs")
    if len(cfg.split_levels) > 1:
        add("Enclosure", "Fiber distribution hub (FDH) cabinet", sp[sp.level == 0].node.nunique(), "pcs")
        add("Enclosure", "Fiber access terminal (FAT)", sp[sp.level == sp.level.max()].node.nunique(), "pcs")
    else:
        add("Enclosure", "Splitter closure", sp.node.nunique(), "pcs")
    feeder_m = float(cables.loc[cables.tier == "feeder", "length_m"].sum())
    add("Enclosure", "Splice closure (inline joints)", int(feeder_m // cfg.splice_every_m), "pcs")

    trench = design.summary_stats["trench_m"]
    add("Civil", "Trench / duct route", round(trench), "m")
    add("Civil", "Handhole / manhole", math.ceil(trench / cfg.handhole_spacing_m) if trench else 0, "pcs")

    ports = int(design.summary_stats["pon_ports"])
    add("Active", "OLT PON port", ports, "ports")
    add("Active", f"OLT line card ({cfg.olt_ports_per_card} PON ports)", math.ceil(ports / cfg.olt_ports_per_card), "pcs")
    add("Active", "ONT / ONU", len(design.premises), "pcs")
    add("Passive", "Fast connector SC/APC (drop ends)", 2 * len(design.premises), "pcs")

    bom = pd.DataFrame(rows, columns=["category", "item", "quantity", "unit"])
    if unit_costs:
        bom["unit_cost"] = bom["item"].map(unit_costs)
        bom["cost"] = bom["unit_cost"] * bom["quantity"]
    return bom

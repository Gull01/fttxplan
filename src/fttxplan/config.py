"""Design parameters and engineering reference values."""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

#: Typical maximum insertion loss of a planar lightwave circuit (PLC) splitter, in dB,
#: including uniformity. Values follow common vendor datasheets for G.671 compliant parts.
SPLITTER_LOSS_DB: dict[int, float] = {2: 3.7, 4: 7.3, 8: 10.5, 16: 13.7, 32: 17.1, 64: 20.5}

#: Standard loose tube cable fibre counts, smallest first.
CABLE_SIZES: tuple[int, ...] = (12, 24, 48, 96, 144, 288)

#: Optical budget of common PON optics classes, in dB.
PON_CLASSES: dict[str, float] = {"B+": 28.0, "C+": 32.0, "C++": 35.0}


def parse_split(value: str | int | tuple[int, ...] | list[int]) -> tuple[int, ...]:
    """Parse a split architecture into a tuple of splitter ratios, from the OLT outward.

    Accepts ``"1:32"``, ``"1:4x1:8"``, ``"1:4,1:8"``, ``"4,8"``, ``32`` or ``(4, 8)``.

    >>> parse_split("1:4x1:8")
    (4, 8)
    >>> parse_split(32)
    (32,)
    """
    if isinstance(value, int):
        ratios: tuple[int, ...] = (value,)
    elif isinstance(value, (tuple, list)):
        ratios = tuple(int(v) for v in value)
    else:
        parts = [p for p in re.split(r"[x×,+\s]+", str(value).strip().lower()) if p]
        ratios = tuple(int(p.split(":")[-1]) for p in parts)
    if not ratios:
        raise ValueError(f"Could not parse split architecture {value!r}")
    for r in ratios:
        if r not in SPLITTER_LOSS_DB:
            raise ValueError(f"Unsupported splitter ratio 1:{r}. Use one of {sorted(SPLITTER_LOSS_DB)}")
    total = 1
    for r in ratios:
        total *= r
    if total > 128:
        raise ValueError(f"Total split 1:{total} is beyond what GPON/XGS-PON optics support (max 1:128)")
    return ratios


@dataclass(frozen=True)
class DesignConfig:
    """All tunable parameters of a design. Every field has a sensible default.

    Lengths are in metres, losses in dB.
    """

    #: Splitter ratios from the OLT outward. ``(4, 8)`` means a 1:4 splitter in a cabinet (FDH)
    #: feeding up to four 1:8 splitters in access terminals (FAT), i.e. 1:32 overall.
    split_levels: tuple[int, ...] = (4, 8)
    #: How many first-level splitters share one FDH cabinet (multi-level designs only).
    #: With ``(4, 8)`` and 8 splitters per cabinet, one cabinet serves up to 256 premises.
    cabinet_size: int = 8
    #: Spare fibres added on top of the fibres actually used, as a fraction (0.2 = 20 %).
    spare_ratio: float = 0.2
    #: Extra cable ordered for slack loops, sag and termination, as a fraction of route length.
    slack_ratio: float = 0.10
    #: Premises farther than this from the nearest road are flagged as long drops.
    max_drop_m: float = 150.0
    #: Fibre attenuation at 1310 nm, dB per km (ITU-T G.652D cable).
    fiber_loss_db_per_km: float = 0.35
    #: Loss per mated connector pair and the number of connector pairs on a path.
    connector_loss_db: float = 0.5
    n_connectors: int = 4
    #: Loss per fusion splice; one splice per splitter, one at the OLT side, plus one per ``splice_every_m``.
    splice_loss_db: float = 0.1
    splice_every_m: float = 2000.0
    #: Optical budget of the PON optics (GPON class B+ = 28 dB) and the margin to keep in reserve.
    budget_db: float = PON_CLASSES["B+"]
    safety_margin_db: float = 3.0
    #: Spacing between handholes / manholes along the trench, for the bill of materials.
    handhole_spacing_m: float = 200.0
    #: PON ports per OLT line card.
    olt_ports_per_card: int = 16
    #: Search radius (network metres) when placing a splitter at the best road node.
    placement_radius_m: float = 3000.0
    #: Random seed for clustering, so designs are reproducible.
    seed: int = 0
    #: Snapping tolerance used when building the road graph.
    snap_tolerance_m: float = 0.5
    extra: dict = field(default_factory=dict, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "split_levels", parse_split(self.split_levels))
        if not 0 <= self.spare_ratio <= 2:
            raise ValueError("spare_ratio must be between 0 and 2")
        if not 0 <= self.slack_ratio <= 1:
            raise ValueError("slack_ratio must be between 0 and 1")

    @property
    def total_split(self) -> int:
        out = 1
        for r in self.split_levels:
            out *= r
        return out

    @property
    def splitter_loss_db(self) -> float:
        return sum(SPLITTER_LOSS_DB[r] for r in self.split_levels)

    def with_(self, **changes) -> DesignConfig:
        """Return a copy with some fields changed."""
        return replace(self, **changes)


def cable_size_for(fibres: int, sizes: tuple[int, ...] = CABLE_SIZES) -> tuple[int, int]:
    """Return ``(cable_size, number_of_cables)`` needed to carry ``fibres`` fibres.

    >>> cable_size_for(10)
    (12, 1)
    >>> cable_size_for(300)
    (288, 2)
    """
    if fibres <= 0:
        return (0, 0)
    for s in sizes:
        if fibres <= s:
            return (s, 1)
    biggest = sizes[-1]
    return (biggest, -(-fibres // biggest))

"""Optical power (loss) budget."""

from __future__ import annotations

import numpy as np

from .config import DesignConfig


def path_loss_db(length_m, cfg: DesignConfig) -> np.ndarray:
    """End to end loss from the OLT to an ONT for paths of the given lengths.

    loss = fibre attenuation + splitter losses + connectors + splices, where splices are one at
    the OLT side, one per splitter, and one every ``cfg.splice_every_m`` of cable.
    """
    length_m = np.asarray(length_m, dtype=float)
    n_splices = 1 + len(cfg.split_levels) + np.floor(length_m / cfg.splice_every_m)
    return (
        length_m / 1000 * cfg.fiber_loss_db_per_km + cfg.splitter_loss_db + cfg.n_connectors * cfg.connector_loss_db + n_splices * cfg.splice_loss_db
    )


def max_reach_m(cfg: DesignConfig) -> float:
    """Longest path that still keeps the safety margin, in metres."""
    fixed = cfg.splitter_loss_db + cfg.n_connectors * cfg.connector_loss_db + (1 + len(cfg.split_levels)) * cfg.splice_loss_db
    per_km = cfg.fiber_loss_db_per_km + cfg.splice_loss_db * 1000 / cfg.splice_every_m
    room = cfg.budget_db - cfg.safety_margin_db - fixed
    return max(0.0, room / per_km * 1000)

import pytest

from fttxplan.budget import max_reach_m, path_loss_db
from fttxplan.config import DesignConfig


def test_loss_formula():
    cfg = DesignConfig(split_levels="1:32")
    # 1 km: 0.35 fibre + 17.1 splitter + 4 x 0.5 connectors + (1 + 1) x 0.1 splices
    assert float(path_loss_db(1000, cfg)) == pytest.approx(0.35 + 17.1 + 2.0 + 0.2)


def test_extra_splices_every_two_km():
    cfg = DesignConfig()
    assert float(path_loss_db(4500, cfg) - path_loss_db(1000, cfg)) == pytest.approx(3.5 * 0.35 + 2 * 0.1)


def test_max_reach_is_consistent():
    cfg = DesignConfig()
    reach = max_reach_m(cfg)
    assert 5000 < reach < 20000
    assert float(path_loss_db(reach * 0.999, cfg)) <= cfg.budget_db - cfg.safety_margin_db + 0.11


def test_bigger_split_means_shorter_reach():
    assert max_reach_m(DesignConfig(split_levels="1:64")) < max_reach_m(DesignConfig(split_levels="1:16"))

import pytest

from fttxplan.config import DesignConfig, cable_size_for, parse_split


@pytest.mark.parametrize(
    "value, expected",
    [
        ("1:32", (32,)),
        ("1:4x1:8", (4, 8)),
        ("1:4,1:8", (4, 8)),
        ("4,8", (4, 8)),
        (16, (16,)),
        ((2, 8, 4), (2, 8, 4)),
        ("1:8 x 1:8", (8, 8)),
    ],
)
def test_parse_split(value, expected):
    assert parse_split(value) == expected


@pytest.mark.parametrize("bad", ["1:3", "", "1:64x1:4", "abc"])
def test_parse_split_rejects(bad):
    with pytest.raises(ValueError):
        parse_split(bad)


def test_cable_sizes():
    assert cable_size_for(0) == (0, 0)
    assert cable_size_for(12) == (12, 1)
    assert cable_size_for(13) == (24, 1)
    assert cable_size_for(288) == (288, 1)
    assert cable_size_for(289) == (288, 2)


def test_config_defaults_and_copy():
    cfg = DesignConfig()
    assert cfg.split_levels == (4, 8)
    assert cfg.total_split == 32
    assert cfg.splitter_loss_db == pytest.approx(7.3 + 10.5)
    other = cfg.with_(split_levels="1:16", spare_ratio=0.5)
    assert other.split_levels == (16,) and other.spare_ratio == 0.5
    assert cfg.split_levels == (4, 8)  # original untouched


def test_config_validation():
    with pytest.raises(ValueError):
        DesignConfig(spare_ratio=-1)

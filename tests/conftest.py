import matplotlib
import pytest

import fttxplan

matplotlib.use("Agg")


@pytest.fixture(scope="session")
def town():
    return fttxplan.synthetic_town(blocks=3, homes_per_side=4, seed=1)


@pytest.fixture(scope="session")
def design(town):
    roads, homes, olt = town
    return fttxplan.plan(roads, olt, homes, crs=roads.crs)

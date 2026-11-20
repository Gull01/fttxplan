import fttxplan


def test_bundled_demo_runs():
    roads, premises, olt = fttxplan.load_demo()
    assert len(premises) > 1000
    d = fttxplan.plan(roads, olt, premises)
    s = d.summary()
    assert s["premises"] == len(premises)
    assert s["budget_failures"] == 0
    assert s["cabinets"] >= 5

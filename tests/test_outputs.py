import geopandas as gpd
import pyogrio

from fttxplan.cli import main


def test_gpkg_roundtrip(design, tmp_path):
    p = design.to_gpkg(tmp_path / "d.gpkg")
    layers = {name for name, _ in pyogrio.list_layers(p)}
    assert {"olt", "splitters", "premises", "cables", "drops", "trench"} <= layers
    back = gpd.read_file(p, layer="premises")
    assert len(back) == len(design.premises)


def test_geojson_is_wgs84(design, tmp_path):
    files = design.to_geojson(tmp_path / "gj")
    assert len(files) == 6
    assert gpd.read_file(files[0]).crs.to_epsg() == 4326


def test_kml(design, tmp_path):
    p = design.to_kml(tmp_path / "d.kml")
    text = p.read_text(encoding="utf-8")
    assert "<kml" in text and "Feeder cable" in text and "OLT" in text


def test_plots(design):
    ax = design.plot()
    assert ax.get_title()
    ax2 = design.plot(theme="dark", color_premises="margin", show_drops=False)
    assert ax2 is not None
    m = design.explore()
    assert "Feeder cable" in m.get_root().render()


def test_cli_design(town, tmp_path):
    roads, homes, olt = town
    roads.to_file(tmp_path / "roads.gpkg")
    homes.to_file(tmp_path / "homes.gpkg")
    gpd.GeoDataFrame(geometry=[olt], crs=roads.crs).to_file(tmp_path / "olt.gpkg")
    out = tmp_path / "out"
    code = main(
        [
            "design",
            str(tmp_path / "roads.gpkg"),
            str(tmp_path / "homes.gpkg"),
            "--olt-file",
            str(tmp_path / "olt.gpkg"),
            "--split",
            "1:32",
            "-o",
            str(out),
        ]
    )
    assert code == 0
    for name in ("design.gpkg", "design.kml", "bom.csv", "loss_budget.csv", "report.txt", "map.png", "map.html"):
        assert (out / name).exists(), name

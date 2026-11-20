"""Export a design to GIS formats."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .design import Design


def to_gpkg(design: Design, path) -> Path:
    """Write every layer of the design into one GeoPackage (opens directly in QGIS / ArcGIS Pro)."""
    path = Path(path)
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    for name, gdf in design.layers().items():
        if len(gdf):
            gdf.to_file(path, layer=name, driver="GPKG")
    return path


def to_geojson(design: Design, folder) -> list[Path]:
    """Write each layer as a separate GeoJSON file in WGS 84."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for name, gdf in design.layers().items():
        if len(gdf):
            p = folder / f"{name}.geojson"
            gdf.to_crs(4326).to_file(p, driver="GeoJSON")
            out.append(p)
    return out


def to_kml(design: Design, path, include_drops: bool = True) -> Path:
    """Write a styled KML for Google Earth, with folders per layer."""
    import simplekml

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    kml = simplekml.Kml(name="FTTx design")
    L = {k: v.to_crs(4326) for k, v in design.layers().items()}

    f = kml.newfolder(name="OLT")
    for _, r in L["olt"].iterrows():
        p = f.newpoint(name="OLT", coords=[r.geometry.coords[0]], description=f"PON ports: {r.pon_ports}")
        p.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/paddle/red-stars.png"

    colors = {"feeder": "ff356bff", "distribution": "ffb6c42e", "drop": "aab1a59a"}
    widths = {"feeder": 4, "distribution": 2.5, "drop": 1}
    tiers = ["feeder", "distribution"] + (["drop"] if include_drops else [])
    for tier in tiers:
        f = kml.newfolder(name=f"{tier.title()} cable")
        for _, r in L["cables"][L["cables"].tier == tier].iterrows():
            ls = f.newlinestring(coords=list(r.geometry.coords))
            ls.name = f"{tier} {r.cable_size}F" if tier != "drop" else f"{r.fibres_used} drop(s)"
            ls.description = f"fibres used {r.fibres_used}, required {r.fibres_required}, cables {r.n_cables}, {r.length_m:.0f} m"
            ls.style.linestyle.color = colors[tier]
            ls.style.linestyle.width = widths[tier]

    f = kml.newfolder(name="Splitters")
    for _, r in L["splitters"].iterrows():
        p = f.newpoint(name=r.splitter_id, coords=[r.geometry.coords[0]])
        p.description = f"{r.role} 1:{r.ratio}, ports used {r.ports_used}, parent {r.parent_id}"
        p.style.iconstyle.icon.href = (
            "http://maps.google.com/mapfiles/kml/shapes/square.png" if r.level == 0 else "http://maps.google.com/mapfiles/kml/shapes/triangle.png"
        )
        p.style.iconstyle.scale = 1.0 if r.level == 0 else 0.7

    f = kml.newfolder(name="Premises")
    for _, r in L["premises"].iterrows():
        p = f.newpoint(name=str(r.premise_id), coords=[r.geometry.coords[0]])
        p.description = f"FAT {r.fat_id}, path {r.path_m:.0f} m, loss {r.loss_db:.1f} dB, margin {r.margin_db:.1f} dB"
        p.style.iconstyle.icon.href = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
        p.style.iconstyle.scale = 0.5
        p.style.iconstyle.color = "ff00ff00" if r.budget_ok else "ff0000ff"
    kml.save(str(path))
    return path

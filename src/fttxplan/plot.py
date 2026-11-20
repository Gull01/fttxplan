"""Static (matplotlib) and interactive (folium) maps of a design."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .design import Design

AREA_COLORS = [
    "#ffd43b",
    "#ff8787",
    "#74c0fc",
    "#b2f2bb",
    "#e599f7",
    "#ffa94d",
    "#63e6be",
    "#a5d8ff",
    "#fcc2d7",
    "#d8f5a2",
    "#91a7ff",
    "#ffe066",
]

THEMES = {
    "light": {
        "bg": "#ffffff",
        "road": "#d5d9e0",
        "drop": "#9aa5b1",
        "dist": "#1f9e89",
        "feeder": "#e8590c",
        "fat": "#1f9e89",
        "fdh": "#5f3dc4",
        "olt": "#c92a2a",
        "text": "#212529",
        "edge": "#ffffff",
    },
    "dark": {
        "bg": "#0b0e14",
        "road": "#2a303c",
        "drop": "#56606e",
        "dist": "#2ec4b6",
        "feeder": "#ff8c42",
        "fat": "#2ec4b6",
        "fdh": "#b197fc",
        "olt": "#ff6b6b",
        "text": "#e9ecef",
        "edge": "#0b0e14",
    },
}


def _width(size, base):
    return base + 0.55 * math.log2(max(size, 12) / 12)


def plot_design(
    design: Design,
    ax=None,
    theme: str = "light",
    show_drops: bool = True,
    color_premises: str = "area",
    figsize=(10, 10),
    title: bool = True,
    legend: bool = True,
):
    """Draw the design: roads, trench and cables (width grows with fibre count), drops,
    splitters, premises and the OLT. ``color_premises`` is ``"area"`` (by cabinet service area,
    the default), ``"fat"`` (by serving terminal) or ``"margin"`` (by optical margin).
    Returns the matplotlib Axes.
    """
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    pal = THEMES[theme]
    if ax is None:
        fig, ax = plt.subplots(figsize=figsize)
        fig.patch.set_facecolor(pal["bg"])
    ax.set_facecolor(pal["bg"])
    design.network.edges_gdf().plot(ax=ax, color=pal["road"], linewidth=0.8, zorder=1)

    cables = design.cables
    if show_drops and len(design.drops):
        design.drops.plot(ax=ax, color=pal["drop"], linewidth=0.35, alpha=0.7, zorder=2)
    for tier, key, base, z in (("distribution", "dist", 1.2, 3), ("feeder", "feeder", 2.0, 4)):
        sub = cables[cables.tier == tier]
        if len(sub):
            sub.plot(
                ax=ax,
                color=pal[key],
                linewidth=[_width(s * n, base) for s, n in zip(sub.cable_size, sub.n_cables)],
                zorder=z,
                capstyle="round",
            )

    prem = design.premises
    if color_premises == "margin":
        prem.plot(
            ax=ax,
            column="margin_db",
            cmap="RdYlGn",
            vmin=0,
            vmax=max(10, float(prem.margin_db.max())),
            markersize=7,
            zorder=5,
            legend=False,
        )
    else:
        col = "fdh_id" if color_premises == "area" and "fdh_id" in prem.columns else "fat_id"
        codes = prem[col].astype("category").cat.codes.to_numpy()
        colors = AREA_COLORS if col == "fdh_id" else [plt.get_cmap("tab20")(i) for i in range(20)]
        prem.plot(ax=ax, color=[colors[c % len(colors)] for c in codes], markersize=7, zorder=5)

    sp = design.splitters
    last = sp.level.max()
    leaf = sp[sp.level == last]
    leaf.plot(ax=ax, marker="^", color=pal["fat"], markersize=34, edgecolor=pal["edge"], linewidth=0.7, zorder=6)
    if last > 0:
        sp[sp.level == 0].plot(ax=ax, marker="s", color=pal["fdh"], markersize=90, edgecolor=pal["edge"], linewidth=1, zorder=7)
    design.olt.plot(ax=ax, marker="*", color=pal["olt"], markersize=420, edgecolor=pal["edge"], linewidth=1, zorder=8)
    ax.set_axis_off()
    ax.set_aspect("equal")

    if legend:
        h = [
            Line2D([], [], marker="*", ls="", color=pal["olt"], ms=15, label="OLT"),
            Line2D([], [], color=pal["feeder"], lw=3, label="Feeder cable"),
            Line2D([], [], color=pal["dist"], lw=2, label="Distribution cable"),
        ]
        if show_drops:
            h.append(Line2D([], [], color=pal["drop"], lw=1, label="Drop cable"))
        if last > 0:
            h.append(
                Line2D(
                    [],
                    [],
                    marker="s",
                    ls="",
                    color=pal["fdh"],
                    ms=9,
                    label=f"FDH cabinet (1:{sp[sp.level == 0].ratio.iloc[0]} splitters)",
                )
            )
        h.append(Line2D([], [], marker="^", ls="", color=pal["fat"], ms=8, label=f"{leaf.role.iloc[0]} (1:{leaf.ratio.iloc[0]})"))
        h.append(
            Line2D(
                [],
                [],
                marker="o",
                ls="",
                color="#868e96",
                ms=5,
                label="Premises (by cabinet area)" if color_premises == "area" and last > 0 else "Premises",
            )
        )
        lg = ax.legend(handles=h, loc="lower left", frameon=True, fontsize=9)
        lg.get_frame().set_facecolor(pal["bg"])
        lg.get_frame().set_edgecolor(pal["road"])
        for t in lg.get_texts():
            t.set_color(pal["text"])
    if title:
        s = design.summary_stats
        ax.set_title(
            f"{s['premises']} premises · {s['architecture']} · {s['pon_ports']} PON ports · "
            f"trench {s['trench_km']:.1f} km · worst margin {s['worst_margin_db']:.1f} dB",
            color=pal["text"],
            fontsize=11,
        )
    return ax


def plot_budget(design: Design, ax=None, theme: str = "light"):
    """Histogram of optical margin per premise, with the safety margin marked."""
    import matplotlib.pyplot as plt

    pal = THEMES[theme]
    if ax is None:
        _, ax = plt.subplots(figsize=(7, 3.2))
    m = design.premises.margin_db.to_numpy()
    ax.hist(m, bins=30, color=pal["dist"], edgecolor=pal["bg"])
    ax.axvline(
        design.config.safety_margin_db,
        color=pal["olt"],
        ls="--",
        lw=1.5,
        label=f"safety margin {design.config.safety_margin_db:g} dB",
    )
    ax.set_xlabel("Optical margin (dB)")
    ax.set_ylabel("Premises")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    return ax


def explore_design(design: Design, tiles: str | None = "OpenStreetMap", show_drops: bool = False, zoom_start: int = 16):
    """Interactive web map (folium) with toggleable layers and tooltips."""
    import folium

    L = {k: v.to_crs(4326) for k, v in design.layers().items()}
    c = L["olt"].geometry.iloc[0]
    m = folium.Map(location=[c.y, c.x], zoom_start=zoom_start, tiles=tiles, control_scale=True)
    pal = THEMES["light"]

    def lines(gdf, name, color, fields, weight, show=True):
        if not len(gdf):
            return
        g = gdf.copy()
        g["w"] = weight(g) if callable(weight) else weight
        folium.GeoJson(
            g,
            name=name,
            show=show,
            style_function=lambda f, color=color: {"color": color, "weight": f["properties"]["w"], "opacity": 0.9},
            tooltip=folium.GeoJsonTooltip(fields=fields),
        ).add_to(m)

    cab = L["cables"]
    if show_drops:
        lines(
            cab[cab.tier == "drop"][["fibres_used", "length_m", "geometry"]],
            "Drop cables",
            pal["drop"],
            ["fibres_used"],
            1,
            show=True,
        )
    lines(
        cab[cab.tier == "distribution"][["cable_size", "fibres_used", "n_cables", "length_m", "geometry"]],
        "Distribution cable",
        pal["dist"],
        ["cable_size", "fibres_used", "n_cables"],
        lambda g: (2 + np.log2(g.cable_size / 12)).round(1),
    )
    lines(
        cab[cab.tier == "feeder"][["cable_size", "fibres_used", "n_cables", "length_m", "geometry"]],
        "Feeder cable",
        pal["feeder"],
        ["cable_size", "fibres_used", "n_cables"],
        lambda g: (3 + np.log2(g.cable_size / 12)).round(1),
    )

    pm = L["premises"][["premise_id", "fat_id", "path_m", "loss_db", "margin_db", "budget_ok", "geometry"]].copy()
    pm["budget_ok"] = pm["budget_ok"].astype(bool)
    folium.GeoJson(
        pm,
        name="Premises",
        marker=folium.CircleMarker(radius=3, fill=True, fill_opacity=0.9, weight=0),
        style_function=lambda f: {"fillColor": "#2b8a3e" if f["properties"]["budget_ok"] else "#e03131"},
        tooltip=folium.GeoJsonTooltip(fields=["premise_id", "fat_id", "path_m", "loss_db", "margin_db"]),
    ).add_to(m)
    sp = L["splitters"][["splitter_id", "role", "ratio", "ports_used", "parent_id", "level", "geometry"]].copy()
    folium.GeoJson(
        sp,
        name="Splitters",
        marker=folium.CircleMarker(radius=6, fill=True, fill_opacity=1, weight=1, color="#ffffff"),
        style_function=lambda f: {
            "fillColor": pal["fdh"] if f["properties"]["level"] == 0 and len(design.config.split_levels) > 1 else pal["fat"],
            "radius": 8 if f["properties"]["level"] == 0 else 5,
        },
        tooltip=folium.GeoJsonTooltip(fields=["splitter_id", "role", "ratio", "ports_used", "parent_id"]),
    ).add_to(m)
    folium.Marker([c.y, c.x], tooltip=f"OLT · {design.summary_stats['pon_ports']} PON ports", icon=folium.Icon(color="red", icon="star")).add_to(m)
    folium.LayerControl(collapsed=False).add_to(m)
    b = L["premises"].total_bounds
    m.fit_bounds([[b[1], b[0]], [b[3], b[2]]])
    return m

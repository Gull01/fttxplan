"""Regenerate the images used in the README:  python docs/make_figures.py"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import fttxplan  # noqa: E402
from fttxplan.plot import plot_budget  # noqa: E402

OUT = Path(__file__).parent / "images"
OUT.mkdir(exist_ok=True)
roads, premises, olt = fttxplan.load_demo()

# hero
design = fttxplan.plan(roads, olt, premises)
ax = design.plot(theme="dark", figsize=(12, 12))
ax.figure.savefig(OUT / "hero.png", dpi=130, bbox_inches="tight", facecolor=ax.figure.get_facecolor())
plt.close("all")

# optical margin map + histogram
fig = plt.figure(figsize=(13, 6.2))
ax1 = fig.add_axes([0.0, 0.0, 0.55, 1.0])
design.plot(ax=ax1, color_premises="margin", show_drops=False, legend=False, title=False)
ax1.set_title("Optical margin per premise (green = more headroom)", fontsize=11)
ax2 = fig.add_axes([0.62, 0.18, 0.36, 0.62])
plot_budget(design, ax=ax2)
ax2.set_title(f"GPON class B+ budget, worst margin {design.summary()['worst_margin_db']:.1f} dB", fontsize=11)
fig.savefig(OUT / "loss_budget.png", dpi=120, bbox_inches="tight")
plt.close("all")

# architecture comparison
archs = ["1:32", "1:4x1:8", "1:8x1:8"]
fig, axes = plt.subplots(1, 3, figsize=(18, 6.6))
rows = []
for a, ax in zip(archs, axes):
    d = fttxplan.plan(roads, olt, premises, split_levels=a)
    d.plot(ax=ax, show_drops=False, legend=False, title=False)
    s = d.summary()
    ax.set_title(
        f"{s['architecture']}\n{s['pon_ports']} PON ports · trench {s['trench_km']:.1f} km · worst margin {s['worst_margin_db']:.1f} dB", fontsize=11
    )
    rows.append((a, s))
fig.tight_layout()
fig.savefig(OUT / "architectures.png", dpi=110, bbox_inches="tight")
plt.close("all")

for _a, s in rows:
    print(
        f"| {s['architecture']} | {s['pon_ports']} | {sum(s['splitters'].values())} | {s['feeder_km']:.1f} | {s['distribution_km']:.1f} | "
        f"{s['drop_km']:.1f} | {s['trench_km']:.1f} | {s['worst_margin_db']:.1f} |"
    )
print(design.report())
print(design.bom().to_markdown(index=False))

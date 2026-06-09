"""
chart_generator.py
------------------
Generates weekly summary pie charts using matplotlib.

Produces a Discord-dark-themed PNG (in-memory BytesIO buffer)
showing per-user difficulty breakdowns and a group comparison bar chart.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import matplotlib
matplotlib.use("Agg")  # non-interactive backend — must be set before importing pyplot
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Colour palette — matches Discord dark theme
# ---------------------------------------------------------------------------

BG_COLOR      = "#2b2d31"   # Discord dark background
PANEL_COLOR   = "#1e1f22"   # Slightly darker panel
TEXT_COLOR    = "#dbdee1"   # Discord primary text
EASY_COLOR    = "#57f287"   # Discord green
MEDIUM_COLOR  = "#fee75c"   # Discord yellow/gold
HARD_COLOR    = "#ed4245"   # Discord red
ZERO_COLOR    = "#4e5058"   # Muted grey for zero bars


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_week_chart(
    weekly_data: dict[str, dict[str, Any]],
    week_label: str = "This Week",
) -> io.BytesIO:
    """
    Generate a weekly summary chart PNG.

    Args:
        weekly_data: ``{display_name: {easy, medium, hard, total, discord_id}}``
        week_label:  Human-readable label for the chart title.

    Returns:
        A ``BytesIO`` buffer containing the PNG image (seek position = 0).
    """
    users = list(weekly_data.keys())
    n = len(users)

    if n == 0:
        return _empty_chart("No data to display.")

    # ------------------------------------------------------------------
    # Layout: top row = pie charts (one per user), bottom row = bar chart
    # ------------------------------------------------------------------
    pie_cols = min(n, 4)
    pie_rows = (n + pie_cols - 1) // pie_cols

    total_rows = pie_rows + 1   # pies + 1 bar chart row
    fig_width  = max(10, pie_cols * 3.2)
    fig_height = pie_rows * 3.4 + 3.0

    fig = plt.figure(figsize=(fig_width, fig_height), facecolor=BG_COLOR)
    gs  = gridspec.GridSpec(
        total_rows, pie_cols,
        figure=fig,
        hspace=0.55,
        wspace=0.35,
        top=0.90,
        bottom=0.08,
        left=0.06,
        right=0.97,
    )

    fig.suptitle(
        f"📊 Weekly LeetCode Summary — {week_label}",
        color=TEXT_COLOR,
        fontsize=15,
        fontweight="bold",
        y=0.97,
    )

    # ------------------------------------------------------------------
    # Pie charts (one per user)
    # ------------------------------------------------------------------
    for idx, (name, data) in enumerate(weekly_data.items()):
        row = idx // pie_cols
        col = idx % pie_cols
        ax  = fig.add_subplot(gs[row, col])
        ax.set_facecolor(PANEL_COLOR)

        easy   = data.get("easy",   0)
        medium = data.get("medium", 0)
        hard   = data.get("hard",   0)
        total  = data.get("total",  0)

        values = [easy, medium, hard]
        labels = ["Easy", "Medium", "Hard"]
        colors = [EASY_COLOR, MEDIUM_COLOR, HARD_COLOR]

        # Filter out zero slices
        non_zero = [
            (v, l, c)
            for v, l, c in zip(values, labels, colors)
            if v > 0
        ]

        if non_zero:
            vals_nz, labels_nz, colors_nz = zip(*non_zero)
            wedges, _, autotexts = ax.pie(
                vals_nz,
                colors=list(colors_nz),
                autopct="%1.0f%%",
                startangle=90,
                pctdistance=0.75,
                wedgeprops={"linewidth": 1.5, "edgecolor": PANEL_COLOR},
            )
            for at in autotexts:
                at.set_color(BG_COLOR)
                at.set_fontsize(9)
                at.set_fontweight("bold")
        else:
            # All-zero: draw a grey circle
            ax.pie(
                [1],
                colors=[ZERO_COLOR],
                wedgeprops={"linewidth": 1.5, "edgecolor": PANEL_COLOR},
            )
            ax.text(
                0, 0, "0",
                ha="center", va="center",
                color=TEXT_COLOR, fontsize=14, fontweight="bold",
            )

        ax.set_title(
            f"{name}\n{total} solved",
            color=TEXT_COLOR,
            fontsize=10,
            fontweight="bold",
            pad=6,
        )

    # Hide unused pie slots in last row
    for spare in range(n, pie_rows * pie_cols):
        row = spare // pie_cols
        col = spare % pie_cols
        ax  = fig.add_subplot(gs[row, col])
        ax.set_visible(False)

    # ------------------------------------------------------------------
    # Bar chart — grouped Easy / Medium / Hard per user
    # ------------------------------------------------------------------
    bar_ax = fig.add_subplot(gs[pie_rows, :])
    bar_ax.set_facecolor(PANEL_COLOR)
    for spine in bar_ax.spines.values():
        spine.set_edgecolor(BG_COLOR)

    import numpy as np  # local import keeps top-level lean

    x        = np.arange(n)
    bar_w    = 0.22
    easy_v   = [weekly_data[u].get("easy",   0) for u in users]
    medium_v = [weekly_data[u].get("medium", 0) for u in users]
    hard_v   = [weekly_data[u].get("hard",   0) for u in users]

    bar_ax.bar(x - bar_w, easy_v,   width=bar_w, color=EASY_COLOR,   label="Easy",   zorder=3)
    bar_ax.bar(x,         medium_v, width=bar_w, color=MEDIUM_COLOR, label="Medium", zorder=3)
    bar_ax.bar(x + bar_w, hard_v,   width=bar_w, color=HARD_COLOR,   label="Hard",   zorder=3)

    bar_ax.set_xticks(x)
    bar_ax.set_xticklabels(users, color=TEXT_COLOR, fontsize=10)
    bar_ax.tick_params(axis="y", colors=TEXT_COLOR, labelsize=9)
    bar_ax.tick_params(axis="x", colors=BG_COLOR)
    bar_ax.yaxis.grid(True, color=BG_COLOR, linewidth=0.8, zorder=0)
    bar_ax.set_axisbelow(True)
    bar_ax.set_ylabel("Problems", color=TEXT_COLOR, fontsize=9)

    # Value labels on top of bars
    for bars in [
        bar_ax.containers[0],
        bar_ax.containers[1],
        bar_ax.containers[2],
    ]:
        for bar in bars:
            h = bar.get_height()
            if h > 0:
                bar_ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    h + 0.05,
                    str(int(h)),
                    ha="center", va="bottom",
                    color=TEXT_COLOR, fontsize=8, fontweight="bold",
                )

    legend = bar_ax.legend(
        facecolor=PANEL_COLOR,
        edgecolor=BG_COLOR,
        labelcolor=TEXT_COLOR,
        fontsize=9,
        loc="upper right",
    )

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        facecolor=BG_COLOR,
        dpi=130,
        bbox_inches="tight",
    )
    buf.seek(0)
    plt.close(fig)
    logger.debug("Weekly chart generated (%d bytes).", buf.getbuffer().nbytes)
    return buf


# ---------------------------------------------------------------------------
# Profile Donut Chart
# ---------------------------------------------------------------------------

def generate_profile_donut_chart(
    easy: int,
    medium: int,
    hard: int,
    username: str,
) -> io.BytesIO:
    """
    Generate a simple, sleek donut chart for a user's all-time problem breakdown.
    """
    total = easy + medium + hard
    if total == 0:
        return _empty_chart("No data to display.")

    fig, ax = plt.subplots(figsize=(4.5, 4.5), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)

    values = [easy, medium, hard]
    labels = ["Easy", "Medium", "Hard"]
    colors = [EASY_COLOR, MEDIUM_COLOR, HARD_COLOR]

    # Filter out zero slices
    non_zero = [
        (v, l, c)
        for v, l, c in zip(values, labels, colors)
        if v > 0
    ]
    
    vals_nz, labels_nz, colors_nz = zip(*non_zero)
    
    wedges, texts, autotexts = ax.pie(
        vals_nz,
        colors=list(colors_nz),
        autopct="%1.0f%%",
        startangle=90,
        pctdistance=0.80,
        wedgeprops={"linewidth": 2.5, "edgecolor": BG_COLOR, "width": 0.4}, # 'width' creates the donut
    )
    
    for at in autotexts:
        at.set_color(BG_COLOR)
        at.set_fontsize(11)
        at.set_fontweight("bold")
        
    ax.text(
        0, 0, f"{total}\nSolved",
        ha="center", va="center",
        color=TEXT_COLOR, fontsize=14, fontweight="bold",
    )

    buf = io.BytesIO()
    fig.savefig(
        buf,
        format="png",
        facecolor=BG_COLOR,
        dpi=150,
        bbox_inches="tight",
        pad_inches=0.1
    )
    buf.seek(0)
    plt.close(fig)
    return buf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_chart(message: str) -> io.BytesIO:
    """Return a minimal placeholder PNG when there is no data."""
    fig, ax = plt.subplots(figsize=(6, 3), facecolor=BG_COLOR)
    ax.set_facecolor(BG_COLOR)
    ax.text(
        0.5, 0.5, message,
        ha="center", va="center",
        color=TEXT_COLOR, fontsize=14,
        transform=ax.transAxes,
    )
    ax.axis("off")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG_COLOR, dpi=100, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

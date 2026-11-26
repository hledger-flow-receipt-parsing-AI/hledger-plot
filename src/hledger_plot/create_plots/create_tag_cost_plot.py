"""What each tag (event, project) cost, at a glance: one bar per tag."""

from __future__ import annotations

from typing import List

import plotly.graph_objects as go
from plotly.graph_objs._figure import Figure
from typeguard import typechecked

from hledger_plot.views.journal_views import TagCost


@typechecked
def create_tag_cost_figure(
    *, costs: List[TagCost], display_currency: str
) -> Figure:
    """Horizontal bars, the most expensive tag on top.  Clicking a bar
    shows only that tag's transactions (dash_plot)."""
    ordered = list(reversed(costs))  # plotly draws the first bar lowest
    hover: List[str] = []
    for cost in ordered:
        lines = [
            f"<b>{cost.tag}</b>",
            f"{display_currency} {cost.cost:,.2f}",
            f"{cost.transactions} transaction(s)",
        ]
        if cost.description:
            lines.insert(1, cost.description)
        for commodity, value in cost.unconverted.items():
            lines.append(f"+ {commodity} {value:,.2f} (no price)")
        hover.append("<br>".join(lines))
    figure = go.Figure(
        go.Bar(
            x=[cost.cost for cost in ordered],
            y=[cost.tag for cost in ordered],
            orientation="h",
            text=[f"{display_currency} {cost.cost:,.2f}" for cost in ordered],
            textposition="auto",
            hovertext=hover,
            hoverinfo="text",
            marker_color="#2ca02c",
        )
    )
    figure.update_layout(
        title="Cost per tag (events, projects), all time:"
        " click a bar to see only that tag",
        xaxis_title=f"Expenses ({display_currency})",
        height=max(220, 60 + 34 * len(ordered)),
        margin=dict(t=60, b=40, l=160, r=40),
    )
    return figure

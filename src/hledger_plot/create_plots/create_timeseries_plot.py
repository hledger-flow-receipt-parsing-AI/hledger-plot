"""Drill-down time-series plot for a single treemap category.

Shows one bar per transaction and a cumulative line, all-time only.
"""

from __future__ import annotations

import re
import shlex
import subprocess  # nosec
from io import StringIO
from typing import List

import pandas as pd
import plotly.graph_objects as go
from plotly.graph_objs._figure import Figure
from typeguard import typechecked


def _parse_currency_amount(raw: str) -> float:
    """Extract a numeric value from an hledger amount like 'EUR100.00'."""
    raw = re.sub(r"(\d),(\d)", r"\1.\2", raw)
    pairs = re.findall(
        r"([A-Z]{2,})?\s*([-+]?\d+(?:\.\d+)?)", raw
    )
    if pairs:
        return float(pairs[0][1])
    cleaned = re.sub(r"[^0-9.\-+]", "", raw)
    return float(cleaned) if cleaned else 0.0


@typechecked
def _run_hledger_register(
    *,
    journal_filepath: str,
    account_prefix: str,
    display_currency: str,
) -> pd.DataFrame:
    """Run ``hledger register`` for *account_prefix* and return a DataFrame.

    Columns: date, description, account, amount.
    """
    cmd = (
        f"hledger -f {journal_filepath} register"
        f" --output-format csv"
        f" --cost --value=then,{display_currency} --infer-value"
        f" {shlex.quote(account_prefix)}"
    )
    result = subprocess.run(
        shlex.split(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd="/",
    )
    if not result.stdout.strip():
        return pd.DataFrame(columns=["date", "description", "account", "amount"])

    raw = pd.read_csv(StringIO(result.stdout))
    df = pd.DataFrame()
    df["date"] = pd.to_datetime(raw["date"])
    df["description"] = raw["description"].fillna("")
    df["account"] = raw["account"]
    df["amount"] = raw["amount"].apply(_parse_currency_amount)
    return df


@typechecked
def _subcategory_label(*, account: str, prefix: str) -> str:
    """Return the portion of *account* after *prefix*.

    E.g. ``_subcategory_label(account='expenses:food:fruit', prefix='expenses:food')``
    returns ``'fruit'``.  If there is nothing after the prefix the full leaf
    name (last segment) is returned.
    """
    if account.startswith(prefix + ":"):
        remainder = account[len(prefix) + 1:]
        return remainder.split(":")[0] if remainder else account.rsplit(":", 1)[-1]
    return account.rsplit(":", 1)[-1]


@typechecked
def create_category_timeseries(
    *,
    journal_filepath: str,
    account_prefix: str,
    display_currency: str,
) -> Figure:
    """Build a bar + cumulative-line chart for *account_prefix* (all-time).

    Each bar represents one transaction.  Bars are coloured by direct
    subcategory.  A cumulative line is overlaid on a secondary y-axis.
    X-axis is a linear date timeline (gaps in time show as gaps on chart).
    """
    df = _run_hledger_register(
        journal_filepath=journal_filepath,
        account_prefix=account_prefix,
        display_currency=display_currency,
    )

    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title=f"No transactions found for {account_prefix}",
        )
        return fig

    df = df.sort_values("date").reset_index(drop=True)

    # Use absolute amounts (expenses are already positive in register).
    df["abs_amount"] = df["amount"].abs()
    df["cumulative"] = df["abs_amount"].cumsum()

    # Subcategory colour grouping.
    df["subcategory"] = df["account"].apply(
        lambda a: _subcategory_label(account=a, prefix=account_prefix)
    )

    # Assign a distinct colour per subcategory.
    unique_subcats = sorted(df["subcategory"].unique())
    palette = _generate_palette(n=len(unique_subcats))
    colour_map = dict(zip(unique_subcats, palette))
    df["colour"] = df["subcategory"].map(colour_map)

    # Hover text.
    df["hover"] = (
        df["date"].dt.strftime("%Y-%m-%d")
        + "<br>"
        + df["description"]
        + "<br>"
        + df["account"]
        + "<br>"
        + display_currency
        + " "
        + df["abs_amount"].round(2).astype(str)
    )

    fig = go.Figure()

    # Use actual dates for x-axis (linear timeline).
    dates = df["date"]

    # One bar trace per subcategory (for legend grouping).
    for subcat in unique_subcats:
        mask = df["subcategory"] == subcat
        sub = df[mask]
        fig.add_trace(
            go.Bar(
                x=sub["date"],
                y=sub["abs_amount"],
                name=subcat,
                marker_color=colour_map[subcat],
                hovertext=sub["hover"],
                hoverinfo="text",
            )
        )

    # Cumulative line on secondary y-axis.
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=df["cumulative"],
            mode="lines",
            name="Cumulative",
            line=dict(color="black", width=2, dash="dot"),
            yaxis="y2",
            hovertemplate=(
                display_currency + " %{y:,.2f}<extra>Cumulative</extra>"
            ),
        )
    )

    # Weekly and monthly totals as flat step-lines on primary y-axis.
    # Each line is a horizontal step showing the total spent in that
    # calendar week / month.
    daily = df.set_index("date")["abs_amount"].resample("D").sum()
    for freq, label, colour, dash_style in [
        ("W-MON", "Weekly total", "#e377c2", "dash"),
        ("MS", "Monthly total", "#17becf", "longdash"),
    ]:
        period_total = daily.resample(freq).sum()
        if period_total.empty:
            continue
        # Build step coordinates: flat line from period start to next period.
        step_x = []
        step_y = []
        for i, (period_start, total) in enumerate(period_total.items()):
            if i + 1 < len(period_total):
                period_end = period_total.index[i + 1]
            else:
                # Last period: extend to the last transaction date.
                period_end = dates.iloc[-1] + pd.Timedelta(days=1)
            step_x.extend([period_start, period_end])
            step_y.extend([total, total])

        fig.add_trace(
            go.Scatter(
                x=step_x,
                y=step_y,
                mode="lines",
                name=label,
                line=dict(color=colour, width=2, dash=dash_style),
                hovertemplate=(
                    display_currency
                    + " %{y:,.2f}<extra>"
                    + label
                    + "</extra>"
                ),
            )
        )

    # X-axis: linear date axis with max 30 ticks.
    max_ticks = 30
    date_range = dates.iloc[-1] - dates.iloc[0]
    n_transactions = len(dates)
    if n_transactions > max_ticks:
        # Pick evenly spaced dates across the range.
        tick_dates = pd.date_range(
            start=dates.iloc[0], end=dates.iloc[-1], periods=max_ticks
        )
        tick_vals = tick_dates.tolist()
        tick_text = tick_dates.strftime("%Y-%m-%d").tolist()
    else:
        tick_vals = dates.tolist()
        tick_text = dates.dt.strftime("%Y-%m-%d").tolist()

    fig.update_layout(
        title=f"Transactions for: {account_prefix}",
        xaxis=dict(
            type="date",
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=-45,
        ),
        yaxis=dict(
            title=f"Amount ({display_currency})",
            rangemode="tozero",
        ),
        yaxis2=dict(
            title="Cumulative",
            overlaying="y",
            side="right",
            rangemode="tozero",
        ),
        barmode="stack",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=600,
        margin=dict(t=80, b=120),
    )

    return fig


def _generate_palette(*, n: int) -> List[str]:
    """Return *n* distinct hex colours from Plotly's qualitative palette."""
    base = [
        "#636EFA", "#EF553B", "#00CC96", "#AB63FA", "#FFA15A",
        "#19D3F3", "#FF6692", "#B6E880", "#FF97FF", "#FECB52",
    ]
    if n <= len(base):
        return base[:n]
    extended = base[:]
    i = 0
    while len(extended) < n:
        extended.append(base[i % len(base)])
        i += 1
    return extended[:n]

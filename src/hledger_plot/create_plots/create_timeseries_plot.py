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

    # One bar trace per subcategory (for legend grouping).
    for subcat in unique_subcats:
        mask = df["subcategory"] == subcat
        sub = df[mask]
        fig.add_trace(
            go.Bar(
                x=sub.index,
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
            x=df.index,
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

    # Moving averages (weekly = 7-day, monthly = 30-day).
    # Resample to daily totals, compute rolling mean, then map back to
    # the transaction-based x-axis indices.
    daily = df.set_index("date")["abs_amount"].resample("D").sum()
    for window, label, colour, dash_style in [
        (7, "7-day avg", "#e377c2", "dash"),
        (30, "30-day avg", "#17becf", "longdash"),
    ]:
        if len(daily) < window:
            continue
        rolling = daily.rolling(window=window, min_periods=1).mean()
        # Map each transaction date to its rolling value.
        ma_values = rolling.reindex(df["date"].values).values
        fig.add_trace(
            go.Scatter(
                x=df.index,
                y=ma_values,
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

    # X-axis: show dates as tick labels (max 30 to stay readable).
    max_ticks = 30
    all_indices = list(df.index)
    all_labels = df["date"].dt.strftime("%Y-%m-%d").tolist()
    if len(all_indices) > max_ticks:
        step = len(all_indices) / max_ticks
        pick = [int(i * step) for i in range(max_ticks)]
        tick_vals = [all_indices[i] for i in pick]
        tick_text = [all_labels[i] for i in pick]
    else:
        tick_vals = all_indices
        tick_text = all_labels

    fig.update_layout(
        title=f"Transactions for: {account_prefix}",
        xaxis=dict(
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

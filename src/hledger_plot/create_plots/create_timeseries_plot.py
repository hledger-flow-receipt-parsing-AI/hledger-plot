"""Drill-down time-series plot for a single treemap category.

Shows one bar per transaction and a cumulative line, all-time only.
With *stack* ("week" or "month") the transactions of each week or month
are stacked into one column, so they add up to that period's total and
can be held against the weekly or monthly average.
"""

from __future__ import annotations

import re
import shlex
import subprocess  # nosec
from io import StringIO
from typing import List, Optional

# The periods the drill-down can stack transactions per: label, the pandas
# frequency of the period totals (weeks start on Monday) and the share of
# the period a column covers (a little gap between columns).
STACK_PERIODS = {
    "week": ("Weekly", "W-MON"),
    "month": ("Monthly", "MS"),
}
COLUMN_SHARE = 0.9

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
    """Return the hierarchical remainder of *account* after *prefix*.

    E.g. ``_subcategory_label(account='expenses:monthly:abbonnement:phone',
    prefix='expenses:monthly')`` returns ``'abbonnement:phone'``.
    """
    if account.startswith(prefix + ":"):
        remainder = account[len(prefix) + 1:]
        return remainder if remainder else account.rsplit(":", 1)[-1]
    return account.rsplit(":", 1)[-1]


@typechecked
def period_starts(*, dates: pd.Series, period: str) -> pd.Series:
    """The first day of the week (Monday) or month of each date."""
    days = dates.dt.normalize()
    if period == "week":
        return days - pd.to_timedelta(days.dt.weekday, unit="D")
    if period == "month":
        return days - pd.to_timedelta(days.dt.day - 1, unit="D")
    raise ValueError(f"Unknown stack period: {period}")


@typechecked
def period_ends(*, starts: pd.Series, period: str) -> pd.Series:
    """The first day after each week or month that starts at *starts*."""
    if period == "week":
        return starts + pd.Timedelta(days=7)
    if period == "month":
        return starts + pd.offsets.MonthBegin(1)
    raise ValueError(f"Unknown stack period: {period}")


@typechecked
def period_totals(*, daily: pd.Series, frequency: str) -> pd.Series:
    """Totals per period, each labelled with the first day of its period.

    pandas labels "W-MON" weeks with the Monday that ENDS them; the
    columns and step lines are drawn from the first day of a period, so
    weeks are taken from Monday up to (not including) the next Monday.
    """
    if frequency.startswith("W-"):
        return daily.resample(frequency, label="left", closed="left").sum()
    return daily.resample(frequency).sum()


@typechecked
def stacked_columns(*, dates: pd.Series, period: str) -> tuple[list, list]:
    """Centre (x) and width (ms) of the column each transaction is stacked
    into: the week or month of its date."""
    starts = period_starts(dates=dates, period=period)
    ends = period_ends(starts=starts, period=period)
    centres = starts + (ends - starts) / 2
    widths = (ends - starts).dt.total_seconds() * 1000 * COLUMN_SHARE
    return centres.tolist(), widths.tolist()


def _build_disconnected_segments(
    period_total: pd.Series, last_date: pd.Timestamp
) -> tuple[list, list]:
    """Build x/y lists for disconnected horizontal segments."""
    step_x: list = []
    step_y: list = []
    for i, (period_start, total) in enumerate(period_total.items()):
        if i + 1 < len(period_total):
            period_end = period_total.index[i + 1]
        else:
            period_end = last_date + pd.Timedelta(days=1)
        step_x.extend([period_start, period_end, None])
        step_y.extend([total, total, None])
    return step_x, step_y


def _sort_subcategories(
    subcats: list[str],
) -> tuple[list[str], dict[str, tuple[str, str | None]]]:
    """Sort subcategories so hierarchical groups are contiguous.

    Returns:
        sorted_subcats: ordered list of subcategory names.
        group_info: dict mapping each subcat to (legendgroup, grouptitle).
            - Multi-child groups (2+ children): group = first segment,
              grouptitle = first segment.  The parent itself (if present)
              is included in the group.
            - Single-child or flat items: group = "_flat", grouptitle = None.

    Example input::

        ['ah', 'ah:kiosk', 'ah:to_go', 'aldi', 'biomarkt',
         'decathlon:creatine', 'ekoplaza']

    Sorted output order::

        ['ah', 'ah:kiosk', 'ah:to_go', 'aldi', 'biomarkt',
         'decathlon:creatine', 'ekoplaza']

    group_info::

        'ah'                 -> ('ah', 'ah')       # multi-child group
        'ah:kiosk'           -> ('ah', 'ah')
        'ah:to_go'           -> ('ah', 'ah')
        'aldi'               -> ('_flat', None)     # flat
        'biomarkt'           -> ('_flat', None)     # flat
        'decathlon:creatine' -> ('_flat', None)     # single child → flat
        'ekoplaza'           -> ('_flat', None)     # flat
    """
    from collections import defaultdict

    # 1. Bucket by first segment.
    buckets: dict[str, list[str]] = defaultdict(list)
    for sc in subcats:
        first = sc.split(":", 1)[0]
        buckets[first].append(sc)

    # 2. Determine which buckets are "real" groups (2+ members).
    multi_groups: set[str] = set()
    for key, members in buckets.items():
        if len(members) >= 2:
            multi_groups.add(key)

    # 3. Build sorted output: iterate bucket keys alphabetically.
    #    For multi-child groups, emit parent first (if present) then children.
    #    For flat/single-child, emit as-is.
    sorted_subcats: list[str] = []
    group_info: dict[str, tuple[str, str | None]] = {}

    for key in sorted(buckets.keys()):
        members = sorted(buckets[key])
        if key in multi_groups:
            # Emit the bare parent first if it exists, then children.
            parent = [m for m in members if ":" not in m]
            children = [m for m in members if ":" in m]
            ordered = parent + children
            for sc in ordered:
                sorted_subcats.append(sc)
                group_info[sc] = (key, key)
        else:
            # Single member — treat as flat.
            for sc in members:
                sorted_subcats.append(sc)
                group_info[sc] = ("_flat", None)

    return sorted_subcats, group_info


@typechecked
def create_category_timeseries(
    *,
    journal_filepath: str,
    account_prefix: str,
    display_currency: str,
    stack: Optional[str] = None,
) -> Figure:
    """Build a bar + cumulative-line chart for *account_prefix* (all-time).

    Each bar represents one transaction.  Bars are coloured by direct
    subcategory.  A cumulative line is overlaid on a secondary y-axis.
    X-axis is a linear date timeline (gaps in time show as gaps on chart).

    With *stack* ("week" or "month") every transaction is a segment of the
    column of its week or month instead, so a column adds up to that
    period's total.  The zoom stays when *stack* changes (uirevision).

    Two legends:
    - Left (legend): Totals, Averages, Cumulative — each independently toggleable.
    - Right (legend2): Subcategories with hierarchical names.
    """
    if stack is not None and stack not in STACK_PERIODS:
        raise ValueError(f"Unknown stack period: {stack}")
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

    # Use actual signed amounts (expenses are positive in register,
    # asset outflows are negative).
    df["abs_amount"] = df["amount"]
    df["cumulative"] = df["abs_amount"].cumsum()

    # Subcategory colour grouping — full hierarchical remainder.
    df["subcategory"] = df["account"].apply(
        lambda a: _subcategory_label(account=a, prefix=account_prefix)
    )

    # Assign a distinct colour per subcategory.
    unique_subcats = sorted(df["subcategory"].unique())

    # Sort subcategories so hierarchical groups are contiguous.
    # E.g. [ah, ah:kiosk, ah:to_go, aldi, biomarkt, decathlon:creatine]
    # Groups with only 1 child are treated as flat (no group header).
    unique_subcats, group_info = _sort_subcategories(unique_subcats)

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

    # ---- Subcategory bars (legend2 = right side) ----
    # group_info maps each subcat to (legendgroup, legendgrouptitle_text).
    # - Multi-child groups: group="groceries", title="groceries" (on first)
    # - Flat/single-child: group="_flat", title=None
    # Single-click toggles one trace, double-click toggles the group.
    seen_groups: set[str] = set()
    for subcat in unique_subcats:
        mask = df["subcategory"] == subcat
        sub = df[mask]
        lg, lgt = group_info[subcat]
        # Only set group title on the first trace of each group.
        show_title = lgt if lg not in seen_groups else None
        seen_groups.add(lg)
        placement: dict = {"x": sub["date"]}
        if stack is not None:
            # One segment per transaction in the column of its period;
            # bars at the same x stack, also within one trace.
            centres, widths = stacked_columns(dates=sub["date"], period=stack)
            placement = {"x": centres, "width": widths}
        fig.add_trace(
            go.Bar(
                **placement,
                y=sub["abs_amount"],
                name=subcat,
                marker_color=colour_map[subcat],
                marker_line=dict(width=0.5, color="white"),
                hovertext=sub["hover"],
                hoverinfo="text",
                legend="legend2",
                legendgroup=lg,
                legendgrouptitle_text=show_title,
            )
        )

    # ---- Cumulative line (legend = left side) ----
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
            legend="legend",
            legendgroup="Cumulative",
        )
    )

    # ---- Period totals (legend = left side) ----
    daily = df.set_index("date")["abs_amount"].resample("D").sum()

    totals_config = [
        ("W-MON", "Weekly total", "#e377c2", "solid"),
        ("MS", "Monthly total", "#17becf", "solid"),
        ("YS", "Yearly total", "#d62728", "dashdot"),
    ]

    # Stacked per week or month, the columns are those totals; the totals
    # of the other period would only cross them (still in the legend).
    hidden_total = {"week": "MS", "month": "W-MON"}.get(stack or "")
    for freq, label, colour, dash_style in totals_config:
        period_total = period_totals(daily=daily, frequency=freq)
        if period_total.empty:
            continue
        step_x, step_y = _build_disconnected_segments(
            period_total, dates.iloc[-1]
        )
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
                legend="legend",
                legendgroup="Totals",
                legendgrouptitle_text="Totals",
                visible="legendonly" if freq == hidden_total else True,
            )
        )

    # ---- Averages (legend = left side) ----
    monthly_totals = period_totals(daily=daily, frequency="MS")
    weekly_totals = period_totals(daily=daily, frequency="W-MON")

    # Overall weekly average: what the weekly columns are held against.
    if len(weekly_totals) > 0:
        weekly_avg = weekly_totals.mean()
        fig.add_trace(
            go.Scatter(
                x=[dates.iloc[0], dates.iloc[-1]],
                y=[weekly_avg, weekly_avg],
                mode="lines",
                name=f"Weekly avg ({display_currency} {weekly_avg:,.2f})",
                line=dict(color="#e377c2", width=2, dash="dot"),
                hovertemplate=(
                    display_currency + " %{y:,.2f}<extra>Weekly avg</extra>"
                ),
                legend="legend",
                legendgroup="Averages",
                legendgrouptitle_text="Averages",
                visible=True if stack == "week" else "legendonly",
            )
        )

    # Overall monthly average.
    if len(monthly_totals) > 0:
        monthly_avg = monthly_totals.mean()
        fig.add_trace(
            go.Scatter(
                x=[dates.iloc[0], dates.iloc[-1]],
                y=[monthly_avg, monthly_avg],
                mode="lines",
                name=f"Monthly avg ({display_currency} {monthly_avg:,.2f})",
                line=dict(color="#2ca02c", width=2, dash="dot"),
                hovertemplate=(
                    display_currency
                    + " %{y:,.2f}<extra>Monthly avg</extra>"
                ),
                legend="legend",
                legendgroup="Averages",
                legendgrouptitle_text="Averages",
            )
        )

    # Per-year monthly average (disconnected segments per year).
    yearly_monthly_avg = monthly_totals.resample("YS").mean()
    if len(yearly_monthly_avg) > 0:
        step_x, step_y = _build_disconnected_segments(
            yearly_monthly_avg, dates.iloc[-1]
        )
        fig.add_trace(
            go.Scatter(
                x=step_x,
                y=step_y,
                mode="lines",
                name="Yearly monthly avg",
                line=dict(color="#9467bd", width=2, dash="dot"),
                hovertemplate=(
                    display_currency
                    + " %{y:,.2f}<extra>Yearly monthly avg</extra>"
                ),
                legend="legend",
                legendgroup="Averages",
            )
        )

    # X-axis: linear date axis with max 30 ticks.
    max_ticks = 30
    n_transactions = len(dates)
    if n_transactions > max_ticks:
        tick_dates = pd.date_range(
            start=dates.iloc[0], end=dates.iloc[-1], periods=max_ticks
        )
        tick_vals = tick_dates.tolist()
        tick_text = tick_dates.strftime("%Y-%m-%d").tolist()
    else:
        tick_vals = dates.tolist()
        tick_text = dates.dt.strftime("%Y-%m-%d").tolist()

    title = f"Transactions for: {account_prefix}"
    if stack is not None:
        title += f" (stacked per {stack})"
    fig.update_layout(
        title=title,
        # Plotly keeps the user's zoom while this stays the same, so
        # stacking and unstacking keeps the zoomed-in stretch of time.
        uirevision=account_prefix,
        xaxis=dict(
            type="date",
            tickmode="array",
            tickvals=tick_vals,
            ticktext=tick_text,
            tickangle=-45,
            # The zoomed-in stretch of time stays when stacking toggles...
            uirevision=account_prefix,
        ),
        yaxis=dict(
            title=f"Amount ({display_currency})",
            rangemode="tozero",
            # ...while the heights fit the columns or bars again.
            uirevision=f"{account_prefix}|{stack}",
        ),
        yaxis2=dict(
            title="Cumulative",
            overlaying="y",
            side="right",
            rangemode="tozero",
            uirevision=f"{account_prefix}|{stack}",
        ),
        # "relative": refunds (negative) stack below the axis in a column.
        barmode="relative" if stack is not None else "stack",
        # Left legend: totals, averages, cumulative.
        # groupclick="toggleitem" means single-click toggles one trace,
        # double-click toggles entire group.
        legend=dict(
            title="Lines",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="right",
            x=-0.05,
            groupclick="toggleitem",
        ),
        # Right legend: subcategories.
        # groupclick="toggleitem" means single-click toggles one trace,
        # double-click toggles entire group.
        legend2=dict(
            title="Categories",
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=1.02,
            groupclick="toggleitem",
        ),
        height=600,
        margin=dict(t=80, b=120, l=200, r=180),
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

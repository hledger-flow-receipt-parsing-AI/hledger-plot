from argparse import Namespace
from typing import Dict, List

import matplotlib.colors as mcolors
import plotly.express as px
from pandas.core.frame import DataFrame
from plotly.graph_objs._figure import Figure
from typeguard import typechecked

from hledger_plot.create_plots.scrambler import scramble_sankey_data
from hledger_plot.HledgerCategories import get_parent
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.time_filtering.TimePeriod import TimePeriod


def check_negative_assets(df, identifier: str, time_period: TimePeriod):
    # Look at original values in column 1 before abs() was applied
    negative_assets = df[
        (df[0].str.startswith(identifier)) & (df[1].astype(int) < 0)
    ]

    if time_period.all_time:
        if not negative_assets.empty:
            problematic_assets = negative_assets[[0, 1]].values.tolist()
            # Create formatted string with name-value pairs on new lines.
            error_details = "\n".join(
                f"{name}: {value}" for name, value in problematic_assets
            )
            raise ValueError(
                f"Negative values found for assets:\n{error_details}\nAsset"
                " values should not be negative. (Probably your opening"
                " balance is incorrect or set for a different account."
            )


@typechecked
def add_to_value_of_category(
    *, df: DataFrame, entry_name: str, amount: float
) -> None:
    """Adds the specified amount to the value of the given entry in the
    DataFrame.

    Args:
        df: The DataFrame containing the data.
        entry_name: The name of the entry to modify.
        amount: The amount to add to the entry's value.

    Raises:
        ValueError: If the entry_name is not found in the DataFrame.
    """

    try:
        df.loc[df[0] == entry_name, 1] += amount
    except KeyError:
        raise ValueError(f"Did not find entry_name:{entry_name}")


@typechecked
def get_values_of_children(*, df: DataFrame, child_name: str) -> float:
    some = df.loc[df[0] == child_name, 1]
    if len(some) != 1:
        raise ValueError("returning something other than a single number.")
    some_float: float = float(some.iloc[0])
    return some_float


def get_level_dict(df: DataFrame) -> Dict[int, List[str]]:
    children: Dict[int, List[str]] = {}
    for category in df[0]:
        if category != "":

            if category.count(":") in children.keys():
                children[category.count(":")].append(category)
            else:
                children[category.count(":")] = [category]
        else:
            raise ValueError(f"Empty categories not supported:{category}")
    for key, value in children.items():
        children[key] = list(set(value))
    return children


@typechecked
def get_max_level_to_min_level(
    ordered_children: Dict[int, List[str]],
) -> List[int]:
    return sorted(ordered_children.keys())


@typechecked
def set_parent_to_child_sum(*, df: DataFrame) -> None:
    ordered_entries: Dict[int, List[str]] = get_level_dict(df=df)
    levels: List[int] = get_max_level_to_min_level(
        ordered_children=ordered_entries
    )
    for level in reversed(levels):
        for ordered_entry in ordered_entries[level]:
            if level > 0:

                # get parent, make its value its current value plus this value.
                add_to_value_of_category(
                    df=df,
                    entry_name=get_parent(ordered_entry),
                    amount=get_values_of_children(
                        df=df, child_name=ordered_entry
                    ),
                )


def _fix_parent_child_sums(*, df: DataFrame) -> None:
    """Set each parent's 'value' to the sum of its children's 'value'.

    Walks from the deepest level upward so that leaf values are authoritative
    and every non-leaf equals the sum of its direct children.  This ensures
    the ``branchvalues='total'`` invariant that Plotly treemaps require.
    """
    ordered = get_level_dict(df=df)
    for level in sorted(ordered.keys(), reverse=True):
        for entry in ordered[level]:
            children = df.loc[df["parent"] == entry, "value"]
            if not children.empty:
                df.loc[df[0] == entry, "value"] = children.sum()


def combined_treemap_plot(
    *,
    args: Namespace,
    balances_df: DataFrame,
    account_categories: List[str],
    title: str,
    plot_config: PlotConfig,
    time_period: TimePeriod,
    skip_negative_check: bool = False,
) -> Figure:
    # Filter the DataFrame for the specified categories
    filtered_df = balances_df[
        balances_df[0].str.contains("|".join(account_categories))
    ].copy()  # Make a copy to avoid modifying the original DataFrame

    if len(set(filtered_df[0])) != len(filtered_df[0]):
        raise ValueError("Found dupes.")

    max_depth = get_max_depth_from_treemap_labels(list(filtered_df[0]))
    # Prepare the DataFrame
    filtered_df.loc[:, "name"] = filtered_df[0]
    filtered_df.loc[:, "value"] = abs(filtered_df[1].astype(int))
    filtered_df.loc[:, "parent"] = filtered_df["name"].apply(get_parent)

    if not skip_negative_check:
        check_negative_assets(
            df=filtered_df, identifier="assets", time_period=time_period
        )

    # Recompute parent values as sum of children so the treemap
    # branchvalues='total' invariant holds after abs()/int().
    _fix_parent_child_sums(df=filtered_df)

    if args.randomize:
        scramble_sankey_data(
            sankey_df=filtered_df,
            random_words=plot_config.random_words,
            top_level_categories=account_categories,
            separator=plot_config.separator,
            text_column_headers=[0],
            numeric_column_headers=[1],
        )

        if len(set(filtered_df[0])) != len(filtered_df[0]):
            raise ValueError("Found dupes after randomization.")

        set_parent_to_child_sum(df=filtered_df)
        filtered_df.loc[:, "name"] = filtered_df[0]
        filtered_df.loc[:, "value"] = abs(filtered_df[1].astype(int))
        filtered_df.loc[:, "parent"] = filtered_df["name"].apply(get_parent)

    # Create the treemap
    fig = px.treemap(
        data_frame=filtered_df,
        names="name",
        parents="parent",
        values="value",
        branchvalues="total",
        title=f"{title} {account_categories}",
    )

    # after creating `fig` with px.treemap(...)
    fig.update_traces(
        marker=dict(
            colors=[category_color(max_depth, n) for n in filtered_df["name"]],
            line=dict(width=1, color="white"),
        ),
        hovertemplate="<b>%{label}</b><br>Value: %{value}<br><extra></extra>",
    )

    fig.layout.meta = "treemap"
    return fig


def get_max_depth_from_treemap_labels(labels: List[str]) -> int:
    """
    Given a list of treemap labels (e.g. from fig.data[0].labels),
    return the maximum number of ':' characters in any label.
    This corresponds to the deepest hierarchy level (excluding top-level).
    """
    if not labels:
        return 0
    return max(label.count(":") for label in labels)


# ----------------------------------------------------------------------
# Helper – linear interpolation between two hex colours
# ----------------------------------------------------------------------
def _make_ramp(n_steps: int, light_hex: str, dark_hex: str):
    """Return a list of `n_steps` hex colours from light → dark."""
    if n_steps <= 1:
        return [light_hex]
    light = mcolors.to_rgb(light_hex)
    dark = mcolors.to_rgb(dark_hex)
    return [
        mcolors.to_hex(
            [
                light[i] + (dark[i] - light[i]) * (j / (n_steps - 1))
                for i in range(3)
            ]
        )
        for j in range(n_steps)
    ]


# ----------------------------------------------------------------------
# Main colour function
# ----------------------------------------------------------------------
def category_color(max_depth: int, name: str) -> str:
    """
    Return a hex colour for a treemap rectangle.

    * depth == 0  → **lightest** colour (root is now light)
    * depth == max_depth → **darkest** colour
    * The branch (blue vs red) is taken from the first segment of the name.
    """
    depth = name.count(":")  # current node depth

    first_segment = name.split(":", 1)[0].lower()
    is_blue = any(k in first_segment for k in ["income", "asset"])

    # --------------------------------------------------------------
    # 3. Build a ramp that has `max_depth + 1` steps
    #    index 0 = very light, index max_depth = dark
    # --------------------------------------------------------------
    n_steps = max_depth + 1
    if is_blue:
        ramp = _make_ramp(
            n_steps, light_hex="#e6f2ff", dark_hex="#0066cc"  # very light blue
        )  # deep blue
    else:
        ramp = _make_ramp(
            n_steps, light_hex="#ffe6e6", dark_hex="#cc0000"  # very light red
        )  # deep red

    # --------------------------------------------------------------
    # 4. Map depth → ramp index (root = lightest)
    # --------------------------------------------------------------
    idx = min(depth, max_depth)  # safety clamp
    return ramp[idx]  # depth 0 → ramp[0] (lightest)

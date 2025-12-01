import copy
from argparse import Namespace
from pathlib import Path
from typing import Dict, List

import pandas as pd
from pandas.core.frame import DataFrame
from plotly.graph_objs import Figure
from plotly.subplots import make_subplots
from typeguard import typechecked

from hledger_plot.create_plots.create_sankey_plot import (
    pysankey_plot_with_manual_pos,
    to_sankey_df,
)
from hledger_plot.create_plots.create_treemap_plot import combined_treemap_plot
from hledger_plot.create_plots.labels_with_values import format_treemap_labels
from hledger_plot.create_plots.Plots import ExtendedPlots, Plots
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.time_filtering.add_dropdown import add_dropdown
from hledger_plot.time_filtering.TimePeriod import TimePeriod

# from plotly.graph_objs._figure import Figure


@typechecked
def create_plot_objects(
    *,
    args: Namespace,
    all_balances_df: DataFrame,
    plot_config: PlotConfig,
    income_expenses_df: DataFrame,
    net_worth_df: DataFrame,
    time_period: TimePeriod,
) -> ExtendedPlots:
    net_worth_treemap: Figure = combined_treemap_plot(
        args=args,
        balances_df=net_worth_df,
        account_categories=[
            plot_config.hledgerCategories.liability_categories,  # liabliities are shown but not scrambled.
            plot_config.hledgerCategories.asset_categories,  # Assets are not shown but are scrambled.
        ],
        plot_config=plot_config,
        title="Treemap - Your financial state/position:",
        time_period=time_period,
    )

    net_worth_sankey: pd.DataFrame = to_sankey_df(
        args=args,
        df=all_balances_df,
        desired_left_top_level_categories=[
            plot_config.hledgerCategories.liability_categories
        ],
        desired_right_top_level_categories=[
            plot_config.hledgerCategories.asset_categories
        ],
        plot_config=plot_config,
    )

    # Get all balances plot.
    all_balances_sankey_man_pos: Figure = pysankey_plot_with_manual_pos(
        sankey_df=net_worth_sankey,
        title="Sankey plot - How your assets cover your liabilities:",
    )

    # Create the income vs expense Sankey plot.
    income_vs_expenses_sankey_df: pd.DataFrame = to_sankey_df(
        args=args,
        df=income_expenses_df,
        desired_left_top_level_categories=[
            plot_config.hledgerCategories.income_categories
        ],
        desired_right_top_level_categories=[
            plot_config.hledgerCategories.expense_categories
        ],
        plot_config=plot_config,
    )
    income_expenses_sankey_man_pos: Figure = pysankey_plot_with_manual_pos(
        sankey_df=income_vs_expenses_sankey_df,
        title=(
            "Sankey plot - Change over time: how your income covered your"
            " expenses:"
        ),
    )

    # Generate the Treemap plot for the expenses.
    income_vs_expenses_treemap: Figure = combined_treemap_plot(
        args=args,
        balances_df=income_expenses_df,
        account_categories=[
            plot_config.hledgerCategories.income_categories,
            plot_config.hledgerCategories.expense_categories,
        ],
        title=(
            "Treemap - Change over time: how your income covered your expenses:"
        ),
        plot_config=plot_config,
        time_period=time_period,
    )

    expenses_treemap: Figure = combined_treemap_plot(
        args=args,
        balances_df=income_expenses_df,
        account_categories=[plot_config.hledgerCategories.expense_categories],
        title="Treemap - Overview of your expenses:",
        time_period=time_period,
        plot_config=plot_config,
    )
    income_treemap: Figure = combined_treemap_plot(
        args=args,
        balances_df=income_expenses_df,
        account_categories=[plot_config.hledgerCategories.income_categories],
        title="Treemap - Overview of your income:",
        plot_config=plot_config,
        time_period=time_period,
    )
    extended_plots: ExtendedPlots = ExtendedPlots(
        net_worth_treemap=net_worth_treemap,
        plots=Plots(
            income_vs_expenses_treemap=income_vs_expenses_treemap,
            expenses_treemap=expenses_treemap,
            income_treemap=income_treemap,
            all_balances_sankey_man_pos=all_balances_sankey_man_pos,
            income_expenses_sankey_man_pos=income_expenses_sankey_man_pos,
        ),
    )
    return extended_plots


@typechecked
def show_plots(
    *,
    args: Namespace,
    some_figs: List[Figure],
) -> None:
    if args.show_plots:

        specs: List[List[Dict[str, str]]] = []
        for i, some_fig in enumerate(some_figs):
            specs.append([{"type": some_fig.layout.meta}])
        subplot_titles = [fig.layout.title.text for fig in some_figs]
        # Display all three graphs in a column.
        fig = make_subplots(
            rows=len(some_figs),
            cols=1,
            specs=specs,
            subplot_titles=subplot_titles,
        )
        for i, some_fig in enumerate(some_figs):
            # Expenses treemap first
            fig.add_trace(some_fig.data[0], row=i + 1, col=1)
            fig.update_xaxes(title_text=some_fig.layout.title, row=i + 1)

        add_dropdown(fig=fig, some_figs=some_figs)
        fig.update_layout(
            title_text="Insight in financial situation",
            # TODO: Scale the 2800 len per image with the max nr. of entries in
            # levels dict for Sankey.
            height=len(some_figs) * 900,
        )

        fig.show()


@typechecked
def export_plots(
    *,
    args: Namespace,
    plot_config: PlotConfig,
    extended_plots: "ExtendedPlots",  # forward reference – real type elsewhere
    time_period: "TimePeriod",  # forward reference
) -> None:
    """Create the required folder tree and export the selected plots."""

    # ------------------------------------------------------------------- #
    # 4.2  Sub-folder definitions (one source of truth)
    # ------------------------------------------------------------------- #
    subfolders: List[str] = [
        "income_expenses_sankey",
        "all_balances_sankey",
        "income_vs_expenses_treemap",
        "expenses_treemap",
        "net_worth_treemap",
    ]

    # ------------------------------------------------------------------- #
    # 4.3  Create the whole tree *once* (only if we actually export)
    # ------------------------------------------------------------------- #
    do_export = args.export_sankey or args.export_treemap
    if do_export:
        for sub in subfolders:
            (plot_config.base_path / sub).mkdir(parents=True, exist_ok=True)

    period_str = time_period.get_period()

    # ------------------------------------------------------------------- #
    # 4.5  Export Sankey plots
    # ------------------------------------------------------------------- #
    if args.export_sankey:
        for enum_name, (attr, sub) in plot_config.sankey_map.items():
            fig = getattr(extended_plots.plots, attr)
            export_treemap_to_svg(
                plot_config=plot_config,
                fig=fig,
                filepath=plot_path(
                    base_dir=plot_config.base_path,
                    sub_dir=sub,
                    period=period_str,
                ),
            )

    # ------------------------------------------------------------------- #
    # 4.6  Export Treemap plots
    # ------------------------------------------------------------------- #
    if args.export_treemap:
        # The original code exported *all* treemaps, even the one called `net_worth_treemap`
        # which lives under `extended_plots.net_worth_treemap` (outside `plots`).
        for enum_name, (attr, sub) in plot_config.treemap_map.items():
            fig = getattr(extended_plots.plots, attr, None) or getattr(
                extended_plots, attr
            )

            # MODIFICATION: Format labels with path and value

            fig = format_treemap_labels(
                fig=fig, disp_currency=plot_config.disp_currency
            )

            export_treemap_to_svg(
                plot_config=plot_config,
                fig=fig,
                filepath=plot_path(
                    base_dir=plot_config.base_path,
                    sub_dir=sub,
                    period=period_str,
                ),
            )


# --------------------------------------------------------------------------- #
# 2. Helper to build a full SVG path
# --------------------------------------------------------------------------- #
@typechecked
def plot_path(*, base_dir: Path, sub_dir: str, period: str) -> Path:
    """<base_dir>/<sub_dir>/<period>.svg"""
    return base_dir / sub_dir / f"{period}.svg"


# --------------------------------------------------------------------------- #
# 3. SVG exporter (unchanged logic, just a tiny bit tidier)
# --------------------------------------------------------------------------- #
@typechecked
def export_treemap_to_svg(
    *,
    plot_config: PlotConfig,
    fig: Figure,
    filepath: Path,
    max_width: int = 2000,
    max_height: int = 1500,
) -> None:
    """
    Export a Plotly treemap/sankey to SVG (no title, no margins, fixed size).

    The parent directory is created automatically.
    """
    filepath.parent.mkdir(parents=True, exist_ok=True)

    fig_clean = copy.deepcopy(fig)
    fig_clean.update_layout(
        title=None,
        margin=dict(l=0, r=0, t=0, b=0),
        autosize=False,
        width=max_width,
        height=max_height,
        paper_bgcolor="white",
        plot_bgcolor="white",
    )

    fig_clean.write_image(str(filepath), format="svg")

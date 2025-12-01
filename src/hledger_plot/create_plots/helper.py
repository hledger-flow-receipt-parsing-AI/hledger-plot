# import plotly
from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from hledger_plot.create_plots.manage_plotting import (
    create_plot_objects,
    plot_path,
)
from hledger_plot.create_plots.Plots import ExtendedPlots
from hledger_plot.parse_journal import read_balance_report
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.time_filtering.TimePeriod import TimePeriod


def run_pipeline(
    *,
    args,
    plot_config: PlotConfig,
    time_period: TimePeriod,
) -> ExtendedPlots:
    """Return the six Plotly Figures that `show_plots` used to display."""

    # ---- 1. balance data ----------------------------------------------------
    all_balances_df = read_balance_report(
        args=args,
        top_level_account_categories=plot_config.top_level_account_categories,
        time_period=time_period,
    )

    # ---- 2. income vs expense -----------------------------------------------
    income_vs_expenses_df = read_balance_report(
        args=args,
        top_level_account_categories=plot_config.top_level_account_categories,
        time_period=time_period,
    )

    # ---- 3. net-worth -------------------------------------------------------
    net_worth_df = read_balance_report(
        args=args,
        top_level_account_categories=plot_config.top_level_account_categories,
        time_period=time_period,
        is_net_worth=True,
    )

    # ---- 4. create the six Plotly objects -----------------------------------
    extended_plots: ExtendedPlots = create_plot_objects(
        args=args,
        all_balances_df=all_balances_df,
        income_expenses_df=income_vs_expenses_df,
        net_worth_df=net_worth_df,
        plot_config=plot_config,
        time_period=time_period,
    )

    return extended_plots


def one_of_the_output_images_does_not_yet_exist(
    *,
    base_path: Path,
    time_period: TimePeriod,
    plot_config: PlotConfig,
    args: Namespace,
) -> bool:
    """
    Return True if *any* of the selected output SVGs is missing.

    Checks only the plot types that are requested via CLI flags:
      - args.export_sankey  → check Sankey SVGs
      - args.export_treemap → check Treemap SVGs
    """
    period_str = time_period.get_period()

    # ------------------------------------------------------------------- #
    # 1. Treemap SVGs
    # ------------------------------------------------------------------- #
    if getattr(args, "export_treemap", False):
        for enum_name, (attr, sub_dir) in plot_config.treemap_map.items():
            svg_path: Path = plot_path(
                base_dir=base_path, sub_dir=sub_dir, period=period_str
            )
            if not svg_path.exists():
                return True  # at least one missing → yes

    # ------------------------------------------------------------------- #
    # 2. Sankey SVGs
    # ------------------------------------------------------------------- #
    if getattr(args, "export_sankey", False):
        for enum_name, (attr, sub_dir) in plot_config.sankey_map.items():
            svg_path: Path = plot_path(
                base_dir=base_path, sub_dir=sub_dir, period=period_str
            )
            if not svg_path.exists():
                return True  # at least one missing → yes

    # ------------------------------------------------------------------- #
    # 3. All exist → no work needed
    # ------------------------------------------------------------------- #
    return False

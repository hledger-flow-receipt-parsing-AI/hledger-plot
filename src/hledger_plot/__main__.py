"""Entry point for the project."""

import os
from typing import Any, Dict

from hledger_core.Currency import Currency
from typeguard import typechecked

from hledger_plot.arg_parser import create_arg_parser, verify_args
from hledger_plot.create_plots.helper import (
    one_of_the_output_images_does_not_yet_exist,
    run_pipeline,
)
from hledger_plot.create_plots.manage_plotting import export_plots
from hledger_plot.create_plots.Plots import ExtendedPlots
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.plotting_dash.dash_plot import launch_dash_dashboard
from hledger_plot.time_filtering.get_available_periods import (
    get_years_and_months_from_hledger,
)
from hledger_plot.time_filtering.TimePeriod import TimePeriod


@typechecked
def main() -> None:
    # For the Sankey diagram,  top-level accounts need to be connected to the
    #  special bucket that divides input from output. The name for this bucket
    # is randomly chosen to be: BALANCE-LINE.

    parser = create_arg_parser()

    args: Any = verify_args(parser=parser)

    plot_config: PlotConfig = PlotConfig(args=args)
    if args.journal_filepath:

        export_plots_for_all_times(
            args=args,
            plot_config=plot_config,
        )

        # Support SKIP_DASH environment variable for testing
        if os.environ.get("SKIP_DASH", "false").lower() != "true":
            launch_dash_dashboard(
                args=args,
                plot_config=plot_config,
            )
        else:
            print("SKIP_DASH=true: Skipping Dash dashboard launch")


def export_plots_for_all_times(
    args,
    plot_config: PlotConfig,
):
    years_and_months: Dict[int, set[int]] = get_years_and_months_from_hledger(
        filepath=args.journal_filepath
    )

    # ------------------------------------------------------------------- #
    # 4.1  Base directories (hash of the journal guarantees uniqueness)
    # ------------------------------------------------------------------- #

    for year, months in years_and_months.items():
        for month in months:

            time_period = TimePeriod(
                filename=args.journal_filepath,
                account_categories=" ".join(
                    plot_config.top_level_account_categories
                ),
                disp_currency=Currency(args.display_currency),
                month=month,
                year=year,
                all_time=False,
            )

            # Check if target file exists.
            if one_of_the_output_images_does_not_yet_exist(
                base_path=plot_config.base_path,
                time_period=time_period,
                plot_config=plot_config,
                args=args,
            ):
                print(
                    f"Exporting for:\n{plot_config.journal_hash} and"
                    f" period:\n{time_period.get_period()}"
                )

                extended_plots: ExtendedPlots = run_pipeline(
                    args=args,
                    plot_config=plot_config,
                    time_period=time_period,
                )

                # import pickle
                # Save (pickle)
                # with open("extended_plots.pkl", "wb") as f:
                #     pickle.dump(extended_plots, f)
                # Load (unpickle)
                # with open("extended_plots.pkl", "rb") as f:
                #     extended_plots = pickle.load(f)

                export_plots(
                    args=args,
                    plot_config=plot_config,
                    extended_plots=extended_plots,
                    time_period=time_period,
                    # config=plot_config.config,
                )


if __name__ == "__main__":
    main()

# --------------------------------------------------------------
#  dashboard.py   (or paste it at the end of your main file)
# --------------------------------------------------------------
from __future__ import annotations

from dash import Dash, Input, Output, dcc, html
from hledger_preprocessor.Currency import Currency
from typeguard import typechecked

from hledger_plot.create_plots.helper import run_pipeline
from hledger_plot.create_plots.Plots import ExtendedPlots
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.time_filtering.get_available_periods import (
    get_years_and_months_from_hledger,
)
from hledger_plot.time_filtering.TimePeriod import TimePeriod

# ------------------------------------------------------------------
# Helper: turn "Jan 2025" → (month_int, year_int)
# ------------------------------------------------------------------
_MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]


def _parse_period(period_str: str) -> tuple[int, int]:
    month_str, year_str = period_str.split()
    # month = _MONTHS.index(month_str) + 1
    month = int(month_str)
    if month < 1:
        raise ValueError(f"Cannot have month smaller than 1. Found:{month}.")
    if month > 12:
        raise ValueError(f"Cannot have month larger than 12. Found:{month}.")
    year = int(year_str)
    return month, year


# ------------------------------------------------------------------
# 1. The public entry point
# ------------------------------------------------------------------
@typechecked
def launch_dash_dashboard(
    *,
    args,
    plot_config: PlotConfig,
) -> None:
    """
    Starts a Dash server that shows the financial dashboard.
    The dropdown updates the whole pipeline (TimePeriod → plots → export).
    """

    # --------------------------------------------------------------
    # 2. Build the dropdown options (once)
    # --------------------------------------------------------------
    years_and_months: dict[int, set[int]] = get_years_and_months_from_hledger(
        filepath=args.journal_filepath
    )

    options: list[dict[str, str]] = []
    for year in years_and_months.keys():
        for month in years_and_months[year]:
            options.append(
                {
                    "label": f"{_MONTHS[month-1]} {year}",
                    "value": f"{month} {year}",
                }
            )
    options.insert(
        0, {"label": "All Time", "value": "all_time"}
    )  # <-- add option

    # --------------------------------------------------------------
    # 3. Dash layout
    # --------------------------------------------------------------
    app = Dash(__name__, suppress_callback_exceptions=True)

    app.layout = html.Div(
        [
            html.H1("Financial Insights Dashboard", style={"margin": "20px"}),
            html.Label("Select Period:", style={"marginLeft": "20px"}),
            dcc.Dropdown(
                id="period-dropdown",
                options=options,
                value="all_time",  # default to All Time
                style={"width": "260px", "margin": "10px 20px"},
            ),
            html.Div(id="plots-container", style={"marginTop": "20px"}),
        ]
    )

    # --------------------------------------------------------------
    # 4. Callback – re-run *everything* when the dropdown changes
    # --------------------------------------------------------------
    @app.callback(
        Output("plots-container", "children"),
        Input("period-dropdown", "value"),
    )
    def _update_dashboard(selected_period: str):
        if selected_period == "all_time":
            time_period = TimePeriod(
                filename=args.journal_filepath,
                account_categories=" ".join(
                    plot_config.top_level_account_categories
                ),
                disp_currency=Currency(args.display_currency),
                month=None,
                year=None,
                all_time=True,
            )
        else:
            month, year = _parse_period(selected_period)
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

        # ---- run the heavy pipeline (returns list[Figure]) --------------------
        extended_plots: ExtendedPlots = run_pipeline(
            args=args,
            plot_config=plot_config,
            time_period=time_period,
        )
        # ---- stitch the figures together with correct heights -----------------
        return _render_combined(extended_plots=extended_plots)

    # --------------------------------------------------------------
    # 5. Start the server
    # --------------------------------------------------------------
    # `debug=False` in production, `use_reloader=False` when called from a script
    app.run(debug=True, use_reloader=False)


# ------------------------------------------------------------------
# 6. The pipeline (exactly the same code you already have)
# ------------------------------------------------------------------
def _render_combined(extended_plots: ExtendedPlots):
    if not extended_plots:
        return html.Div("No plots generated.")

    graphs = []
    for i, fig in enumerate(extended_plots.get_plots_as_list()):
        # Ensure each figure has a height
        height = fig.layout.height or 900
        title = (
            fig.layout.title.text
            if fig.layout.title and fig.layout.title.text
            else f"Plot {i+1}"
        )

        # Wrap in a Div with title and padding
        graph = html.Div(
            [
                html.H3(
                    title,
                    style={"margin": "20px 0 10px 0", "textAlign": "center"},
                ),
                dcc.Graph(
                    figure=fig.update_layout(
                        height=height, margin=dict(t=40, b=40)
                    ),
                    style={"width": "100%", "height": f"{height}px"},
                ),
            ],
            style={"marginBottom": "40px"},
        )
        graphs.append(graph)

    return html.Div(graphs)

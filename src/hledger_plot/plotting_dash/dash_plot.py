# --------------------------------------------------------------
#  Financial Insights Dashboard with treemap drill-down
#
#  "Drill-down Mode" button  ->  click treemap cell  ->  time-series
#  "Back to Overview" button ->  return to treemaps
# --------------------------------------------------------------
from __future__ import annotations

import json
from typing import Any

from dash import ALL, Dash, Input, Output, State, callback_context, dcc, html
from dash.exceptions import PreventUpdate
from hledger_preprocessor.Currency import Currency
from typeguard import typechecked

from hledger_plot.create_plots.create_timeseries_plot import (
    create_category_timeseries,
)
from hledger_plot.create_plots.helper import run_pipeline
from hledger_plot.create_plots.Plots import ExtendedPlots
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.time_filtering.get_available_periods import (
    get_years_and_months_from_hledger,
)
from hledger_plot.time_filtering.TimePeriod import TimePeriod

# ------------------------------------------------------------------
# Helper: turn "Jan 2025" -> (month_int, year_int)
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
    args: Any,
    plot_config: PlotConfig,
) -> None:
    """
    Starts a Dash server that shows the financial dashboard.
    The dropdown updates the whole pipeline (TimePeriod -> plots -> export).

    Click "Drill-down Mode" then click any treemap cell to see a
    time-series view showing one bar per transaction and a cumulative line.
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

    _btn_base = {
        "padding": "8px 16px",
        "fontSize": "14px",
        "cursor": "pointer",
        "borderRadius": "4px",
        "border": "1px solid #ccc",
    }
    _btn_inactive = {**_btn_base, "backgroundColor": "#f0f0f0", "color": "#333"}
    _btn_active = {**_btn_base, "backgroundColor": "#1a73e8", "color": "white"}
    _hidden = {"display": "none"}

    app.layout = html.Div(
        [
            html.H1("Financial Insights Dashboard", style={"margin": "20px"}),
            html.Div(
                [
                    html.Label(
                        "Select Period:",
                        style={"marginRight": "8px"},
                    ),
                    dcc.Dropdown(
                        id="period-dropdown",
                        options=options,
                        value="all_time",  # default to All Time
                        style={"width": "260px"},
                    ),
                    html.Button(
                        "Drill-down Mode",
                        id="drilldown-mode-btn",
                        n_clicks=0,
                        style={**_btn_inactive, "marginLeft": "20px"},
                    ),
                    html.Span(
                        id="drilldown-hint",
                        children="",
                        style={
                            "marginLeft": "10px",
                            "fontSize": "13px",
                            "color": "#888",
                            "alignSelf": "center",
                        },
                    ),
                ],
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "margin": "10px 20px",
                },
            ),
            # Back-bar: sits above plots-container, hidden until drill-down.
            html.Div(
                id="back-bar",
                style=_hidden,
                children=[
                    html.Button(
                        "Back to Overview",
                        id="back-btn",
                        n_clicks=0,
                        style=_btn_inactive,
                    ),
                    html.Span(
                        id="drilldown-label",
                        style={
                            "marginLeft": "12px",
                            "fontSize": "16px",
                            "fontWeight": "bold",
                        },
                    ),
                ],
            ),
            # All plots live here — overview OR drill-down (swapped in-place).
            html.Div(id="plots-container", style={"marginTop": "20px"}),
            # Hidden stores.
            dcc.Store(id="drilldown-mode-store", data=json.dumps(False)),
            dcc.Store(id="overview-cache", data=""),
        ]
    )

    # --------------------------------------------------------------
    # 4. Callback: period change -> re-run pipeline -> render plots
    # --------------------------------------------------------------
    @app.callback(
        Output("plots-container", "children"),
        Output("overview-cache", "data"),
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

        extended_plots: ExtendedPlots = run_pipeline(
            args=args,
            plot_config=plot_config,
            time_period=time_period,
        )
        children = _render_combined(extended_plots=extended_plots)
        return children, selected_period

    # --------------------------------------------------------------
    # 5. Toggle drill-down mode on/off
    # --------------------------------------------------------------
    @app.callback(
        Output("drilldown-mode-store", "data"),
        Output("drilldown-mode-btn", "style"),
        Output("drilldown-hint", "children"),
        Input("drilldown-mode-btn", "n_clicks"),
        State("drilldown-mode-store", "data"),
        prevent_initial_call=True,
    )
    def _toggle_drilldown_mode(n_clicks, current_mode_json):
        current = json.loads(current_mode_json)
        new_mode = not current
        if new_mode:
            return (
                json.dumps(True),
                {**_btn_active, "marginLeft": "20px"},
                "Click any treemap cell to drill down",
            )
        return (
            json.dumps(False),
            {**_btn_inactive, "marginLeft": "20px"},
            "",
        )

    # --------------------------------------------------------------
    # 6. Drill-down: treemap clickData (mode on) or Back btn
    #    Swaps plots-container between overview and drill-down.
    # --------------------------------------------------------------
    @app.callback(
        Output("plots-container", "children", allow_duplicate=True),
        Output("back-bar", "style"),
        Output("drilldown-label", "children"),
        # Reset mode after drill-down.
        Output("drilldown-mode-store", "data", allow_duplicate=True),
        Output("drilldown-mode-btn", "style", allow_duplicate=True),
        Output("drilldown-hint", "children", allow_duplicate=True),
        Input("back-btn", "n_clicks"),
        Input({"type": "treemap-graph", "index": ALL}, "clickData"),
        State("drilldown-mode-store", "data"),
        State("period-dropdown", "value"),
        prevent_initial_call=True,
    )
    def _handle_drilldown(
        back_clicks, all_click_data, mode_json, current_period
    ):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"]
        mode_off = (
            json.dumps(False),
            {**_btn_inactive, "marginLeft": "20px"},
            "",
        )

        # Back button -> re-render overview from current period.
        if "back-btn" in trigger_id:
            period = current_period or "all_time"
            if period == "all_time":
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
                m, y = _parse_period(period)
                time_period = TimePeriod(
                    filename=args.journal_filepath,
                    account_categories=" ".join(
                        plot_config.top_level_account_categories
                    ),
                    disp_currency=Currency(args.display_currency),
                    month=m,
                    year=y,
                    all_time=False,
                )
            extended_plots: ExtendedPlots = run_pipeline(
                args=args,
                plot_config=plot_config,
                time_period=time_period,
            )
            overview = _render_combined(extended_plots=extended_plots)
            return (overview, _hidden, "", *mode_off)

        # A treemap was clicked — only act if drill-down mode is on.
        mode_on = json.loads(mode_json)
        if not mode_on:
            raise PreventUpdate

        # Find which graph actually triggered.
        label = None
        triggered_id = ctx.triggered_id
        if isinstance(triggered_id, dict) and triggered_id.get("type") == "treemap-graph":
            idx = triggered_id.get("index", -1)
            if 0 <= idx < len(all_click_data):
                cd = all_click_data[idx]
                if cd and cd.get("points"):
                    label = cd["points"][0].get("label", "")

        if not label:
            raise PreventUpdate

        fig = create_category_timeseries(
            journal_filepath=args.journal_filepath,
            account_prefix=label,
            display_currency=args.display_currency,
        )

        drilldown_view = html.Div(
            [
                dcc.Graph(
                    figure=fig,
                    style={
                        "width": "100%",
                        "height": "600px",
                        "margin": "0 20px",
                    },
                ),
            ]
        )
        back_bar_style = {
            "display": "flex",
            "alignItems": "center",
            "margin": "10px 20px",
        }

        return (
            drilldown_view,
            back_bar_style,
            f"Drill-down: {label}",
            *mode_off,
        )

    # --------------------------------------------------------------
    # 7. Start the server
    # --------------------------------------------------------------
    app.run(debug=True, use_reloader=False)


# ------------------------------------------------------------------
# 8. Render overview plots
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
                    id={"type": "treemap-graph", "index": i},
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

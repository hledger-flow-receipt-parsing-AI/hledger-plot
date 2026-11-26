# --------------------------------------------------------------
#  Financial Insights Dashboard with treemap drill-down
#
#  "Drill-down Mode" button  ->  click treemap cell  ->  time-series
#  "Back to Overview" button ->  return to treemaps
#  Keyboard shortcut 'd' toggles drill-down mode.
#  Granularity selector: Weekly / Monthly / Yearly / All Time.
#  Top right: a tag (event, project) and who can see the transactions
#  (both / traceable / untraceable), see hledger_plot.views.
#  Drill-down, top right: "Stack" piles the transactions of every week or
#  month into one column (the zoom stays).
# --------------------------------------------------------------
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

from dash import (
    ALL,
    Dash,
    Input,
    Output,
    State,
    callback_context,
    dcc,
    html,
    no_update,
)
from dash.exceptions import PreventUpdate
from hledger_core.Currency import Currency
from typeguard import typechecked

from hledger_plot.create_plots.create_tag_cost_plot import (
    create_tag_cost_figure,
)
from hledger_plot.create_plots.create_timeseries_plot import (
    create_category_timeseries,
)
from hledger_plot.create_plots.helper import run_pipeline
from hledger_plot.create_plots.Plots import ExtendedPlots
from hledger_plot.PlotConfig import PlotConfig
from hledger_plot.plotting_dash.port_check import dash_host_and_port
from hledger_plot.time_filtering.get_available_periods import (
    get_years_and_months_from_hledger,
)
from hledger_plot.time_filtering.TimePeriod import TimePeriod
from hledger_plot.views.journal_views import (
    BOTH,
    TRACEABLE,
    UNTRACEABLE,
    JournalViews,
    default_traceable_accounts,
    describe_view,
    tag_options,
)

log = logging.getLogger(__name__)

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


def _build_period_options(
    years_and_months: dict[int, set[int]],
) -> dict[str, list[dict[str, str]]]:
    """Build dropdown options for each granularity level.

    Returns a dict keyed by "weekly", "monthly", "yearly".
    Each value is a list of {label, value} dicts.
    """
    # Monthly options (existing behaviour).
    monthly: list[dict[str, str]] = []
    for year in sorted(years_and_months.keys()):
        for month in sorted(years_and_months[year]):
            monthly.append(
                {
                    "label": f"{_MONTHS[month-1]} {year}",
                    "value": f"m:{month} {year}",
                }
            )

    # Yearly options.
    yearly: list[dict[str, str]] = []
    for year in sorted(years_and_months.keys()):
        yearly.append({"label": str(year), "value": f"y:{year}"})

    # Weekly options — enumerate ISO weeks that contain transactions.
    all_dates: list[datetime] = []
    for year, months in years_and_months.items():
        for month in months:
            # Use the 15th as representative; we just need to generate
            # week boundaries covering each month.
            dt = datetime(year, month, 1)
            while dt.month == month:
                all_dates.append(dt)
                dt += timedelta(days=1)
    if all_dates:
        min_date = min(all_dates)
        max_date = max(all_dates)
    else:
        min_date = max_date = datetime.now()

    # Walk week by week from the Monday on/before min_date.
    monday = min_date - timedelta(days=min_date.weekday())
    weekly: list[dict[str, str]] = []
    while monday <= max_date:
        sunday = monday + timedelta(days=6)
        label = f"{monday.strftime('%d %b')} - {sunday.strftime('%d %b %Y')}"
        # value encodes start and end as YYYY/M/D
        value = (
            f"w:{monday.year}/{monday.month}/{monday.day}"
            f":{sunday.year}/{sunday.month}/{sunday.day}"
        )
        weekly.append({"label": label, "value": value})
        monday += timedelta(days=7)

    return {"weekly": weekly, "monthly": monthly, "yearly": yearly}


def _make_time_period(
    selected_period: str,
    *,
    args: Any,
    plot_config: PlotConfig,
    journal_filepath: Optional[str] = None,
) -> TimePeriod:
    """Create a TimePeriod from a dropdown value string, for the journal of
    the view (the whole journal by default)."""
    account_cats = " ".join(plot_config.top_level_account_categories)
    currency = Currency(args.display_currency)
    filename = journal_filepath or args.journal_filepath
    partial_view = filename != args.journal_filepath

    if selected_period == "all_time":
        return TimePeriod(
            filename=filename,
        partial_view=partial_view,
            account_categories=account_cats,
            disp_currency=currency,
            month=None,
            year=None,
            all_time=True,
        )

    prefix = selected_period[:2]

    if prefix == "m:":
        month, year = _parse_period(selected_period[2:])
        return TimePeriod(
            filename=filename,
        partial_view=partial_view,
            account_categories=account_cats,
            disp_currency=currency,
            month=month,
            year=year,
            all_time=False,
        )

    if prefix == "y:":
        year = int(selected_period[2:])
        return TimePeriod(
            filename=filename,
        partial_view=partial_view,
            account_categories=account_cats,
            disp_currency=currency,
            month=None,
            year=year,
            all_time=False,
        )

    if prefix == "w:":
        # "w:YYYY/M/D:YYYY/M/D"
        parts = selected_period[2:].split(":")
        start_str = parts[0]  # YYYY/M/D
        end_str = parts[1]  # YYYY/M/D
        # End date for hledger is exclusive, so add 1 day.
        ey, em, ed = (int(x) for x in end_str.split("/"))
        end_excl = datetime(ey, em, ed) + timedelta(days=1)
        end_hledger = f"{end_excl.year}/{end_excl.month}/{end_excl.day}"
        return TimePeriod(
            filename=filename,
        partial_view=partial_view,
            account_categories=account_cats,
            disp_currency=currency,
            month=None,
            year=None,
            all_time=False,
            start_date=start_str,
            end_date=end_hledger,
            period_label=f"week_{start_str.replace('/', '_')}",
        )

    raise ValueError(f"Unknown period format: {selected_period}")


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

    all_period_options = _build_period_options(years_and_months)

    # Views of the journal: traceable or not (traceability.yaml), and the
    # transactions of one tag (tags.yaml and the journal's own tags).
    views = JournalViews(
        journal_filepath=args.journal_filepath,
        cache_dir=os.path.join(
            str(plot_config.hledger_plot_dir), "views", plot_config.journal_hash
        ),
        root_finance_path=plot_config.config.dir_paths.root_finance_path,
        default_traceable=default_traceable_accounts(config=plot_config.config),
    )
    try:
        tag_names = views.tag_names()
    except (OSError, ValueError, RuntimeError) as error:
        log.warning("Reading the tags failed: %s", error)
        tag_names = []

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

    _sticky_bar = {
        "position": "sticky",
        "top": "0",
        "zIndex": "1000",
        "backgroundColor": "white",
        "borderBottom": "1px solid #ddd",
        "paddingBottom": "8px",
    }

    _granularity_btn = {
        "padding": "4px 12px",
        "fontSize": "13px",
        "cursor": "pointer",
        "borderRadius": "4px",
        "border": "1px solid #ccc",
        "backgroundColor": "#f0f0f0",
        "color": "#333",
        "marginRight": "4px",
    }
    _granularity_btn_active = {
        **_granularity_btn,
        "backgroundColor": "#333",
        "color": "white",
        "border": "1px solid #333",
    }

    app.layout = html.Div(
        [
            # Sticky toolbar.
            html.Div(
                id="sticky-toolbar",
                style=_sticky_bar,
                children=[
                    html.H1(
                        "Financial Insights Dashboard",
                        style={"margin": "10px 20px 4px 20px", "fontSize": "22px"},
                    ),
                    # Row 1: Granularity + Period dropdown + Drill-down button.
                    html.Div(
                        [
                            html.Label(
                                "Granularity:",
                                style={"marginRight": "6px", "fontSize": "13px"},
                            ),
                            html.Button(
                                "Weekly",
                                id="gran-weekly-btn",
                                n_clicks=0,
                                style=_granularity_btn,
                            ),
                            html.Button(
                                "Monthly",
                                id="gran-monthly-btn",
                                n_clicks=0,
                                style=_granularity_btn_active,
                            ),
                            html.Button(
                                "Yearly",
                                id="gran-yearly-btn",
                                n_clicks=0,
                                style=_granularity_btn,
                            ),
                            html.Div(
                                style={"width": "12px", "display": "inline-block"}
                            ),
                            html.Label(
                                "Period:",
                                style={"marginRight": "6px", "fontSize": "13px"},
                            ),
                            dcc.Dropdown(
                                id="period-dropdown",
                                options=[
                                    {"label": "All Time", "value": "all_time"},
                                ]
                                + all_period_options["monthly"],
                                value="all_time",
                                style={"width": "260px"},
                            ),
                            html.Div(
                                style={"width": "20px", "display": "inline-block"}
                            ),
                            html.Button(
                                "Drill-down Mode (d)",
                                id="drilldown-mode-btn",
                                n_clicks=0,
                                style=_btn_inactive,
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
                            # Everything after this sits at the top right.
                            html.Div(style={"flex": "1"}),
                            html.Label(
                                "Tag:",
                                style={"marginRight": "6px", "fontSize": "13px"},
                            ),
                            dcc.Dropdown(
                                id="tag-dropdown",
                                options=tag_options(names=tag_names),
                                value=None,
                                placeholder="All transactions",
                                clearable=True,
                                style={"width": "220px"},
                            ),
                            html.Div(
                                style={"width": "16px", "display": "inline-block"}
                            ),
                            html.Label(
                                "Seen by others:",
                                title=(
                                    "Traceable: a bank, card issuer or exchange"
                                    " keeps a record that links the"
                                    " transaction to you (traceability.yaml)."
                                ),
                                style={"marginRight": "6px", "fontSize": "13px"},
                            ),
                            html.Button(
                                "Both",
                                id="trace-both-btn",
                                n_clicks=0,
                                style=_granularity_btn_active,
                            ),
                            html.Button(
                                "Traceable",
                                id="trace-yes-btn",
                                n_clicks=0,
                                style=_granularity_btn,
                            ),
                            html.Button(
                                "Untraceable",
                                id="trace-no-btn",
                                n_clicks=0,
                                style=_granularity_btn,
                            ),
                        ],
                        style={
                            "display": "flex",
                            "alignItems": "center",
                            "margin": "4px 20px",
                            "flexWrap": "wrap",
                            "gap": "2px",
                        },
                    ),
                    # What the view leaves out (tag, traceability), if anything.
                    html.Div(
                        id="view-caption",
                        children="",
                        style={
                            "margin": "2px 20px",
                            "fontSize": "13px",
                            "color": "#b35900",
                        },
                    ),
                    # Back-bar: sits inside toolbar, hidden until drill-down.
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
                            html.Div(style={"flex": "1"}),
                            # Top right of the drill-down: stack the
                            # transactions of a week or month into a column.
                            html.Button(
                                "Stack",
                                id="stack-btn",
                                n_clicks=0,
                                title=(
                                    "Pile the transactions of every week or"
                                    " month into one column, to hold them"
                                    " against the average (click again to"
                                    " go back)"
                                ),
                                style=_btn_inactive,
                            ),
                            html.Div(
                                style={"width": "8px", "display": "inline-block"}
                            ),
                            html.Button(
                                "per week",
                                id="stack-week-btn",
                                n_clicks=0,
                                style=_granularity_btn,
                            ),
                            html.Button(
                                "per month",
                                id="stack-month-btn",
                                n_clicks=0,
                                style=_granularity_btn_active,
                            ),
                        ],
                    ),
                ],
            ),
            # All plots live here — overview OR drill-down (swapped in-place).
            html.Div(id="plots-container", style={"marginTop": "10px"}),
            # Hidden stores.
            dcc.Store(id="drilldown-mode-store", data=json.dumps(False)),
            dcc.Store(id="overview-cache", data=""),
            dcc.Store(id="granularity-store", data="monthly"),
            dcc.Store(
                id="all-period-options",
                data=json.dumps(all_period_options),
            ),
            # Store incremented by keyboard shortcut to trigger callback.
            dcc.Store(id="keyboard-drilldown-trigger", data=0),
            dcc.Store(id="keyboard-back-trigger", data=0),
            # Who can see the transactions shown: both, traceable, untraceable.
            dcc.Store(id="trace-store", data=BOTH),
            # The account of the drill-down on screen ("" on the overview).
            dcc.Store(id="drilldown-account-store", data=""),
            dcc.Store(id="stack-store", data=False),
            dcc.Store(id="stack-period-store", data="month"),
        ]
    )

    _back_bar_shown = {
        "display": "flex",
        "alignItems": "center",
        "margin": "4px 20px",
    }

    def _view_journal(traceability: Optional[str], tag: Optional[str]):
        """The journal of the view and a caption; the whole journal and the
        error as caption when a rules file is wrong."""
        traceability = traceability or BOTH
        try:
            journal = views.journal_for(traceability=traceability, tag=tag)
        except (OSError, ValueError) as error:
            return args.journal_filepath, f"Rules file error, showing all: {error}"
        return journal, describe_view(traceability=traceability, tag=tag)

    def _render_overview(selected_period, traceability, tag):
        journal, caption = _view_journal(traceability, tag)
        try:
            time_period = _make_time_period(
                selected_period or "all_time",
                args=args,
                plot_config=plot_config,
                journal_filepath=journal,
            )
            extended_plots: ExtendedPlots = run_pipeline(
                args=args,
                plot_config=plot_config,
                time_period=time_period,
            )
        except Exception:  # an empty view or period: say so
            log.exception("Plotting the view failed")
            return html.Div(
                "No transactions to show for this period and view.",
                style={"margin": "20px"},
            ), caption
        tag_figure = None
        if tag is None and tag_names:
            try:
                costs = views.tag_costs(
                    traceability=traceability or BOTH,
                    display_currency=args.display_currency,
                )
            except (OSError, ValueError, RuntimeError) as error:
                log.warning("Costing the tags failed: %s", error)
                costs = []
            if costs:
                tag_figure = create_tag_cost_figure(
                    costs=costs, display_currency=args.display_currency
                )
        children = _render_combined(
            extended_plots=extended_plots, tag_figure=tag_figure
        )
        return children, caption

    def _drilldown_figure(account, traceability, tag, stack, stack_period):
        journal, _ = _view_journal(traceability, tag)
        return create_category_timeseries(
            journal_filepath=journal,
            account_prefix=account,
            display_currency=args.display_currency,
            stack=stack_period if stack else None,
        )

    def _render_drilldown(account, traceability, tag, stack, stack_period):
        fig = _drilldown_figure(account, traceability, tag, stack, stack_period)
        return html.Div(
            [
                dcc.Graph(
                    id="drilldown-graph",
                    figure=fig,
                    style={
                        "width": "100%",
                        "height": "600px",
                        "margin": "0 20px",
                    },
                ),
            ]
        )

    # ----------------------------------------------------------
    # Keyboard shortcuts via injected script.
    # 'd' toggles drill-down mode, 'Escape' clicks back.
    # ----------------------------------------------------------
    app.index_string = app.index_string.replace(
        "</body>",
        """<script>
        document.addEventListener('keydown', function(e) {
            var tag = e.target.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
            // Also skip if the Dash dropdown search input is focused.
            if (e.target.getAttribute('role') === 'combobox') return;
            if (e.key === 'd' || e.key === 'D') {
                e.preventDefault();
                var btn = document.getElementById('drilldown-mode-btn');
                if (btn) btn.click();
            }
            if (e.key === 'Escape') {
                e.preventDefault();
                var back = document.getElementById('back-btn');
                if (back && back.offsetParent !== null) back.click();
            }
        });
        </script></body>""",
    )

    # ----------------------------------------------------------
    # 4a. Granularity button click -> update dropdown options.
    # ----------------------------------------------------------
    @app.callback(
        Output("period-dropdown", "options"),
        Output("period-dropdown", "value"),
        Output("granularity-store", "data"),
        Output("gran-weekly-btn", "style"),
        Output("gran-monthly-btn", "style"),
        Output("gran-yearly-btn", "style"),
        Input("gran-weekly-btn", "n_clicks"),
        Input("gran-monthly-btn", "n_clicks"),
        Input("gran-yearly-btn", "n_clicks"),
        State("all-period-options", "data"),
        prevent_initial_call=True,
    )
    def _change_granularity(
        wk_clicks, mo_clicks, yr_clicks, all_opts_json
    ):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        all_opts = json.loads(all_opts_json)

        gran_map = {
            "gran-weekly-btn": ("weekly", "Weekly"),
            "gran-monthly-btn": ("monthly", "Monthly"),
            "gran-yearly-btn": ("yearly", "Yearly"),
        }
        gran_key, _ = gran_map.get(trigger_id, ("monthly", "Monthly"))
        period_opts = [{"label": "All Time", "value": "all_time"}] + all_opts[
            gran_key
        ]

        styles = []
        for btn_id in [
            "gran-weekly-btn",
            "gran-monthly-btn",
            "gran-yearly-btn",
        ]:
            if btn_id == trigger_id:
                styles.append(_granularity_btn_active)
            else:
                styles.append(_granularity_btn)

        return (period_opts, "all_time", gran_key, *styles)

    # --------------------------------------------------------------
    # 4. Callback: period change -> re-run pipeline -> render plots
    # --------------------------------------------------------------
    @app.callback(
        Output("plots-container", "children"),
        Output("overview-cache", "data"),
        Output("view-caption", "children"),
        Input("period-dropdown", "value"),
        Input("trace-store", "data"),
        Input("tag-dropdown", "value"),
        # The only writer of the plot area: entering or leaving the
        # drill-down changes this store, so a slow overview that was still
        # being made can never cover a drill-down opened after it (Dash
        # drops a callback's outdated answers).
        Input("drilldown-account-store", "data"),
        State("stack-store", "data"),
        State("stack-period-store", "data"),
    )
    def _update_dashboard(
        selected_period, traceability, tag, account, stack, stack_period
    ):
        if account:
            # In the drill-down: show it again for the new view.
            _, caption = _view_journal(traceability, tag)
            drilldown = _render_drilldown(
                account, traceability, tag, stack, stack_period
            )
            return drilldown, selected_period, caption
        children, caption = _render_overview(selected_period, traceability, tag)
        return children, selected_period, caption

    # --------------------------------------------------------------
    # 4b. Who can see the transactions: both / traceable / untraceable
    # --------------------------------------------------------------
    @app.callback(
        Output("trace-store", "data"),
        Output("trace-both-btn", "style"),
        Output("trace-yes-btn", "style"),
        Output("trace-no-btn", "style"),
        Input("trace-both-btn", "n_clicks"),
        Input("trace-yes-btn", "n_clicks"),
        Input("trace-no-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def _set_traceability(both_clicks, yes_clicks, no_clicks):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        choice = {
            "trace-both-btn": BOTH,
            "trace-yes-btn": TRACEABLE,
            "trace-no-btn": UNTRACEABLE,
        }[trigger_id]
        styles = [
            _granularity_btn_active if value == choice else _granularity_btn
            for value in (BOTH, TRACEABLE, UNTRACEABLE)
        ]
        return (choice, *styles)

    # --------------------------------------------------------------
    # 4c. A click on a bar of "Cost per tag" shows only that tag
    # --------------------------------------------------------------
    @app.callback(
        Output("tag-dropdown", "value"),
        Input("tag-cost-graph", "clickData"),
        prevent_initial_call=True,
    )
    def _pick_tag(click_data):
        if not click_data or not click_data.get("points"):
            raise PreventUpdate
        return click_data["points"][0].get("y")

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
                _btn_active,
                "Click any treemap cell to drill down",
            )
        return (
            json.dumps(False),
            _btn_inactive,
            "",
        )

    # --------------------------------------------------------------
    # 6. Drill-down: treemap clickData (mode on) or Back btn
    #    Swaps plots-container between overview and drill-down.
    # --------------------------------------------------------------
    @app.callback(
        Output("back-bar", "style"),
        Output("drilldown-label", "children"),
        # Reset mode after drill-down.
        Output("drilldown-mode-store", "data", allow_duplicate=True),
        Output("drilldown-mode-btn", "style", allow_duplicate=True),
        Output("drilldown-hint", "children", allow_duplicate=True),
        Output("drilldown-account-store", "data"),
        Input("back-btn", "n_clicks"),
        Input({"type": "treemap-graph", "index": ALL}, "clickData"),
        State("drilldown-mode-store", "data"),
        prevent_initial_call=True,
    )
    def _handle_drilldown(back_clicks, all_click_data, mode_json):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate

        trigger_id = ctx.triggered[0]["prop_id"]
        mode_off = (
            json.dumps(False),
            _btn_inactive,
            "",
        )

        # Back button -> the overview (made by _update_dashboard).
        if "back-btn" in trigger_id:
            return (_hidden, "", *mode_off, "")

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

        # The drill-down itself is made by _update_dashboard.
        return (
            _back_bar_shown,
            f"Drill-down: {label}",
            *mode_off,
            label,
        )

    # --------------------------------------------------------------
    # 6b. Stack: the transactions of a week or month in one column, and
    #     back.  Only the figure changes, so the zoom stays.
    # --------------------------------------------------------------
    @app.callback(
        Output("stack-store", "data"),
        Output("stack-period-store", "data"),
        Output("stack-btn", "style"),
        Output("stack-week-btn", "style"),
        Output("stack-month-btn", "style"),
        Output("drilldown-graph", "figure"),
        Input("stack-btn", "n_clicks"),
        Input("stack-week-btn", "n_clicks"),
        Input("stack-month-btn", "n_clicks"),
        State("stack-store", "data"),
        State("stack-period-store", "data"),
        State("drilldown-account-store", "data"),
        State("trace-store", "data"),
        State("tag-dropdown", "value"),
        prevent_initial_call=True,
    )
    def _stack(
        stack_clicks,
        week_clicks,
        month_clicks,
        stack,
        stack_period,
        account,
        traceability,
        tag,
    ):
        ctx = callback_context
        if not ctx.triggered:
            raise PreventUpdate
        trigger_id = ctx.triggered[0]["prop_id"].split(".")[0]
        if trigger_id == "stack-btn":
            stack = not stack
        elif trigger_id == "stack-week-btn":
            stack, stack_period = True, "week"
        elif trigger_id == "stack-month-btn":
            stack, stack_period = True, "month"
        styles = (
            _btn_active if stack else _btn_inactive,
            (
                _granularity_btn_active
                if stack_period == "week"
                else _granularity_btn
            ),
            (
                _granularity_btn_active
                if stack_period == "month"
                else _granularity_btn
            ),
        )
        figure = (
            _drilldown_figure(account, traceability, tag, stack, stack_period)
            if account
            else no_update
        )
        return (stack, stack_period, *styles, figure)

    # --------------------------------------------------------------
    # 7. Start the server
    # --------------------------------------------------------------
    host, port = dash_host_and_port()
    app.run(host=host, port=port, debug=True, use_reloader=False)


# ------------------------------------------------------------------
# 8. Render overview plots
# ------------------------------------------------------------------
def _render_combined(extended_plots: ExtendedPlots, tag_figure: Any = None):
    if not extended_plots:
        return html.Div("No plots generated.")

    graphs = []
    if tag_figure is not None:
        # What every event/project cost; a click on a bar selects the tag.
        graphs.append(
            html.Div(
                [
                    dcc.Graph(
                        id="tag-cost-graph",
                        figure=tag_figure,
                        style={
                            "width": "100%",
                            "height": f"{tag_figure.layout.height}px",
                        },
                    )
                ],
                style={"marginBottom": "20px"},
            )
        )
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

from typing import List

# from plotly.graph_objs import Figure
from plotly.graph_objs._figure import Figure
from typeguard import typechecked


@typechecked
def add_dropdown(*, fig: Figure, some_figs: List[Figure]):
    """Add an interactive dropdown with a console print trigger using Plotly Dash (required for callbacks)."""

    # NOTE:
    # Plotly figures alone (in static HTML or Jupyter) cannot execute Python on interaction.
    # To print to CLI when a dropdown changes, wrap this figure in a Dash app.

    from dash import Dash, Input, Output, dcc, html

    years = [2023, 2024, 2025, 2026]
    months = [
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
    options = [f"{m} {y}" for y in years for m in months]

    app = Dash(__name__)

    app.layout = html.Div(
        [
            dcc.Dropdown(
                id="period-dropdown",
                options=[{"label": opt, "value": opt} for opt in options],
                value="Jan 2025",
                style={"width": "200px"},
            ),
            dcc.Graph(id="main-graph", figure=fig),
        ]
    )

    @app.callback(
        Output("main-graph", "figure"), Input("period-dropdown", "value")
    )
    def update_fig(selected_period):
        month, year = selected_period.split()
        fig.update_layout(title_text=f"Financial Insight: {month} {year}")
        return fig

    app.run(debug=True, port=8050)

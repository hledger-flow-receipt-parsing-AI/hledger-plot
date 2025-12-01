# import plotly
from __future__ import annotations

from plotly.graph_objs._figure import Figure


class Plots:
    def __init__(
        self,
        income_vs_expenses_treemap: Figure,
        expenses_treemap: Figure,
        income_treemap: Figure,
        all_balances_sankey_man_pos: Figure,
        income_expenses_sankey_man_pos: Figure,
    ):
        self.income_vs_expenses_treemap = income_vs_expenses_treemap
        self.expenses_treemap = expenses_treemap
        self.income_treemap = income_treemap
        self.all_balances_sankey_man_pos = all_balances_sankey_man_pos
        self.income_expenses_sankey_man_pos = income_expenses_sankey_man_pos


class ExtendedPlots:
    def __init__(
        self,
        plots: Plots,
        net_worth_treemap: Figure,
    ):
        self.plots: Plots = plots
        self.net_worth_treemap: Figure = net_worth_treemap

    def get_plots_as_list(self) -> list[Figure]:
        return [
            self.plots.income_vs_expenses_treemap,
            self.plots.expenses_treemap,
            self.plots.income_treemap,
            self.plots.all_balances_sankey_man_pos,
            self.plots.income_expenses_sankey_man_pos,
            self.net_worth_treemap,
        ]

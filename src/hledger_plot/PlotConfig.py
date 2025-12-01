# import plotly
from __future__ import annotations

from enum import Enum
from pathlib import Path

from hledger_preprocessor.config.Config import Config
from hledger_preprocessor.config.load_config import (
    load_config,
)
from hledger_preprocessor.Currency import Currency

from hledger_plot.create_plots.scrambler import (
    get_rand_categories,
)
from hledger_plot.HledgerCategories import HledgerCategories
from hledger_plot.journal_parsing.get_top_level_domains import (
    get_top_level_account_categories,
)
from hledger_plot.journal_parsing.list_journal_files import (
    load_and_hash_journal_files,
)


class PlotTypes(Enum):
    SANKEY = "sankey"
    TREEMAP = "treemap"


class TreeMapNames(Enum):
    INCOME_VS_EXPENSES = "income_vs_expenses"
    EXPENSES = "expenses"
    INCOME = "income"


class SankeyNames(Enum):
    ALL_BALANCES = "all_balances"
    INCOME_VS_EXPENSES = "income_vs_expenses"


class PlotConfig:
    def __init__(
        self,
        args,
    ):
        self.export_nrs: bool = (
            True  # Whether to export numbers in the svg plots.
        )
        self.disp_currency: Currency = args.display_currency
        if args.journal_filepath:
            self.journal_filepaths, self.journal_hash = (
                load_and_hash_journal_files(
                    abs_journal_root_filepath=args.journal_filepath
                )
            )
            self.config: Config = load_config(
                config_path=args.config,
                pre_processed_output_dir="None",
            )
            self.hledger_plot_dir: Path = Path(
                self.config.dir_paths.get_path(path_name="hledger_plot_dir")
            )
            self.base_path: Path = self.hledger_plot_dir / self.journal_hash

            self.plot_names: dict[
                PlotTypes, list[TreeMapNames | SankeyNames]
            ] = {
                PlotTypes.TREEMAP: [
                    TreeMapNames.INCOME_VS_EXPENSES,
                    TreeMapNames.EXPENSES,
                    TreeMapNames.INCOME,
                ],
                PlotTypes.SANKEY: [
                    SankeyNames.ALL_BALANCES,
                    SankeyNames.INCOME_VS_EXPENSES,
                ],
            }

            # ------------------------------------------------------------------- #
            # 4.4  Mapping: enum → (attribute name on `extended_plots.plots`, subfolder)
            # ------------------------------------------------------------------- #
            self.sankey_map: dict[SankeyNames, tuple[str, str]] = {
                SankeyNames.INCOME_VS_EXPENSES: (
                    "income_expenses_sankey_man_pos",
                    "income_expenses_sankey",
                ),
                SankeyNames.ALL_BALANCES: (
                    "all_balances_sankey_man_pos",
                    "all_balances_sankey",
                ),
            }

            self.treemap_map: dict[TreeMapNames, tuple[str, str]] = {
                TreeMapNames.INCOME_VS_EXPENSES: (
                    "income_vs_expenses_treemap",
                    "income_vs_expenses_treemap",
                ),
                TreeMapNames.EXPENSES: ("expenses_treemap", "expenses_treemap"),
                TreeMapNames.INCOME: (
                    "net_worth_treemap",
                    "net_worth_treemap",
                ),  # kept for completeness
            }
            self.separator: str = "BALANCE-LINE"
            self.random_wordlist_filepath: str = "random_categories.txt"
            self.random_words: list[str] = get_rand_categories(
                random_wordlist_filepath=self.random_wordlist_filepath
            )

            self.hledgerCategories: HledgerCategories = (
                HledgerCategories.from_args(args=args)
            )

            self.top_level_account_categories: list[str] = (
                get_top_level_account_categories(
                    journal_filepath=args.journal_filepath
                )
            )

        else:
            raise ValueError(
                "Did not receive --journal-filepath, so won't do anything."
            )

from argparse import Namespace
from typing import Optional, Type

from typeguard import typechecked


class HledgerCategories:
    """A class to manage and parse Hledger financial categories.

    Attributes:
        asset_categories (str): Top-level asset categories (default: "assets").
        expense_categories (str): Top-level expense categories (default:
        "expenses").
        liability_categories (str): Top-level liability categories (default:
        "liabilities").
        income_categories (str): Top-level income categories (default:
        "income").
        equity_categories (str): Top-level equity categories (default:
        "equity").
    """

    def __init__(
        self,
        asset_categories: str = "assets",
        expense_categories: str = "expenses",
        liability_categories: str = "liabilities",
        income_categories: str = "income",
        equity_categories: str = "equity",
    ) -> None:
        """Initializes an instance of HledgerCategories with the specified
        categories.

        Args:
            asset_categories (str): Top-level asset categories.
            expense_categories (str): Top-level expense categories.
            liability_categories (str): Top-level liability categories.
            income_categories (str): Top-level income categories.
            equity_categories (str): Top-level equity categories.
        """
        self.asset_categories = asset_categories
        self.expense_categories = expense_categories
        self.liability_categories = liability_categories
        self.income_categories = income_categories
        self.equity_categories = equity_categories

    @classmethod
    def from_args(
        cls: Type["HledgerCategories"], args: Namespace
    ) -> "HledgerCategories":
        """Creates an instance of HledgerCategories from an argparse Namespace.

        Args:
            args (Namespace): Parsed command-line arguments containing
            category overrides.

        Returns:
            HledgerCategories: An instance with categories set from the
            arguments.
        """
        return cls(
            asset_categories=cls._parse_categories(
                args.asset_categories, "assets"
            ),
            expense_categories=cls._parse_categories(
                args.expense_categories, "expenses"
            ),
            liability_categories=cls._parse_categories(
                args.liability_categories, "liabilities"
            ),
            income_categories=cls._parse_categories(
                args.income_categories, "income"
            ),
            equity_categories=cls._parse_categories(
                args.equity_categories, "equity"
            ),
        )

    @staticmethod
    def _parse_categories(categories: Optional[str], default: str) -> str:
        """Parses and formats a category string, falling back to a default if
        None.

        Args:
            categories (Optional[str]): A comma-separated string of categories.
            default (str): The default category if none is provided.

        Returns:
            str: A space-separated string of categories.
        """
        if categories is None:
            return default
        return " ".join(categories.split(","))


@typechecked
def get_parent(transaction_category: str) -> str:
    return ":".join(transaction_category.split(":")[:-1])

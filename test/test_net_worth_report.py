"""Net-worth balances: full account names and market valuation.

Two regressions this guards against:

* hledger >= 1.50 prints ``--tree`` CSV rows as indented leaf names
  ("  bank", "    checking").  hledger-plot filtered rows on the top-level
  category name, so every row below the top level was silently dropped.
* Net worth was valued with ``--cost``.  An account that bought BTC with
  EUR and sold it for USD then shows +EUR and -USD although it holds 0 BTC,
  which tripped the "Negative values found for assets" check.
"""

import shutil
import textwrap
from argparse import Namespace
from pathlib import Path
from typing import Any, Dict

import pytest
from hledger_core.Currency import Currency

import hledger_plot.parse_journal as parse_journal
from hledger_plot.create_plots.create_treemap_plot import (
    check_negative_assets,
)
from hledger_plot.time_filtering.TimePeriod import TimePeriod

pytestmark = pytest.mark.skipif(
    shutil.which("hledger") is None, reason="hledger not on PATH"
)

CATEGORIES = ["assets", "equity", "expenses", "income", "liabilities"]

# Kraken-style round trip: buy BTC with EUR, sell all of it for USD.
CROSS_CURRENCY_TRADE_JOURNAL = """\
2024-01-01 opening
    assets:exchange:EUR      EUR 1000
    equity:opening

2024-01-02 buy btc with eur
    assets:exchange:BTC      0.01 BTC @@ EUR 1000
    assets:exchange:EUR      EUR -1000

2024-01-03 sell btc for usd
    assets:exchange:USD      USD 1200
    assets:exchange:BTC      -0.01 BTC @@ USD 1200
"""


def _write_journal(tmp_path: Path, content: str) -> str:
    journal = tmp_path / "test.journal"
    journal.write_text(textwrap.dedent(content))
    return str(journal)


def _all_time(journal: str) -> TimePeriod:
    return TimePeriod(
        filename=journal,
        account_categories=" ".join(CATEGORIES),
        disp_currency=Currency("EUR"),
        all_time=True,
        month=None,
        year=None,
    )


@pytest.fixture
def fixed_rates(monkeypatch: pytest.MonkeyPatch) -> Dict[str, float]:
    """EUR value of one unit of each currency; avoids network fetches."""
    rates = {"EUR": 1.0, "USD": 0.8, "GBP": 1.2, "BTC": 50000.0}
    monkeypatch.setattr(parse_journal, "_get_rates", lambda _cur: rates)
    return rates


def test_tree_csv_rows_get_full_account_names(tmp_path: Path) -> None:
    journal = _write_journal(
        tmp_path,
        """\
        2024-01-01 opening
            assets:bank:checking     EUR 100
            assets:bank:savings      EUR 50
            equity:opening
        """,
    )
    df = parse_journal._run_hledger_to_df(
        f"hledger -f {journal} balance assets equity --no-total"
        " --output-format csv --tree --no-elide",
        CATEGORIES,
    )

    assert set(df[0]) == {
        "assets",
        "assets:bank",
        "assets:bank:checking",
        "assets:bank:savings",
        "equity",
        "equity:opening",
    }


def test_net_worth_values_a_sold_out_position_at_zero(
    tmp_path: Path, fixed_rates: Dict[str, float]
) -> None:
    journal = _write_journal(tmp_path, CROSS_CURRENCY_TRADE_JOURNAL)
    time_period = _all_time(journal)
    args = Namespace(display_currency="EUR", verbose=False)

    df = parse_journal.read_balance_report(
        args=args,
        top_level_account_categories=CATEGORIES,
        time_period=time_period,
        is_net_worth=True,
    )
    values = dict(zip(df[0], df[1].astype(float)))

    # Holding nothing, the BTC account is either absent or zero.
    assert values.get("assets:exchange:BTC", 0.0) == pytest.approx(
        0.0, abs=0.01
    )
    # 1 BTC traded at EUR 1000 and USD 1200, so USD 1200 is worth EUR 1000.
    assert values["assets:exchange:USD"] == pytest.approx(1000.0, abs=0.01)
    assert not any(
        name.startswith("assets") and value < 0
        for name, value in values.items()
    ), values
    check_negative_assets(df=df, identifier="assets", time_period=time_period)


@pytest.mark.parametrize(
    "period",
    [
        {"month": 1, "year": 2024},
        {"month": None, "year": 2024},
        # A week that starts after the opening balance: net worth still
        # counts everything from the start of the journal.
        {
            "month": None,
            "year": None,
            "start_date": "2024/1/3",
            "end_date": "2024/1/4",
            "period_label": "week_2024_1_3",
        },
    ],
    ids=["month", "year", "week"],
)
def test_net_worth_for_a_month_year_or_week(
    tmp_path: Path, fixed_rates: Dict[str, float], period: Dict[str, Any]
) -> None:
    journal = _write_journal(tmp_path, CROSS_CURRENCY_TRADE_JOURNAL)
    time_period = TimePeriod(
        filename=journal,
        account_categories=" ".join(CATEGORIES),
        disp_currency=Currency("EUR"),
        all_time=False,
        **period,
    )
    args = Namespace(display_currency="EUR", verbose=False)

    df = parse_journal.read_balance_report(
        args=args,
        top_level_account_categories=CATEGORIES,
        time_period=time_period,
        is_net_worth=True,
    )
    values = dict(zip(df[0], df[1].astype(float)))

    assert values["assets:exchange:USD"] == pytest.approx(1000.0, abs=0.01)

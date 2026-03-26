import re
import shlex
import subprocess  # nosec
from argparse import Namespace
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
from hledger_preprocessor.Currencies.fetch_rates import (
    fetch_exchange_rates,
)
from hledger_preprocessor.Currency import (
    Currency,
    load_latest_rates,
)
from pandas.core.frame import DataFrame
from typeguard import typechecked

from hledger_plot.time_filtering.TimePeriod import (
    TimePeriod,
    build_hledger_command_from_earliest_to_period,
)


def _parse_currency_pairs(s: str) -> List[Tuple[str, float]]:
    """Extract (currency, amount) pairs from a raw hledger amount string.

    Example input: ``"EUR100.00, GBP50.00"`` → ``[("EUR", 100.0), ("GBP", 50.0)]``
    """
    s = re.sub(r"(\d),(\d)", r"\1.\2", s)
    pairs = re.findall(
        r"([A-Z]{2,})([\s-]*[-+]?\d+(?:\.\d+)?(?:,\d+)?)", s
    )
    result: List[Tuple[str, float]] = []
    for curr, amt_str in pairs:
        amt_str = amt_str.strip().replace(",", "")
        try:
            result.append((curr, float(amt_str)))
        except ValueError:
            pass
    return result


def _get_rates(disp_currency: str) -> Dict[str, float]:
    """Load exchange rates, fetching missing ones if needed."""
    rates = load_latest_rates(disp_currency)
    all_currencies = {c.value for c in Currency}
    missing = all_currencies - set(rates.keys())
    if missing:
        new_rates, _ = fetch_exchange_rates(base_currency=disp_currency)
        rates.update(new_rates)
    return rates


def _run_hledger_to_df(
    hledger_command: str, top_level_account_categories: List[str]
) -> DataFrame:
    """Run an hledger command and return a filtered two-column DataFrame."""
    process_output = subprocess.run(
        shlex.split(hledger_command),
        stdout=subprocess.PIPE,
        text=True,
        cwd="/",
    ).stdout
    raw_df: DataFrame = pd.read_csv(StringIO(process_output), header=None)
    return raw_df[
        raw_df[0].str.contains("|".join(top_level_account_categories))
    ].copy()


def _expand_multicurrency_rows(
    *,
    raw_df: DataFrame,
    valued_df: DataFrame,
    disp_currency: str,
    rates: Dict[str, float],
) -> DataFrame:
    """Split accounts that hold multiple currencies into virtual sub-accounts.

    For each *leaf* account in *raw_df* whose balance contains 2+ distinct
    currencies, replace the single aggregated row in *valued_df* with one row
    per currency (e.g. ``wallet:physical`` → ``wallet:physical:EUR`` +
    ``wallet:physical:GBP``).

    Only leaf accounts are split — intermediate/parent accounts that show
    multi-currency totals because of their children are left untouched.

    Accounts that already have ``:CURRENCY`` sub-accounts in *valued_df* are
    skipped to avoid duplication.
    """
    all_accounts = set(valued_df[0])

    # Build a set of accounts that are parents of other accounts so we can
    # restrict splitting to leaf accounts only.
    parent_accounts: set = set()
    for acct in all_accounts:
        parts = acct.split(":")
        for i in range(1, len(parts)):
            parent_accounts.add(":".join(parts[:i]))

    new_rows: List[Dict] = []
    accounts_to_zero: List[str] = []

    for _, row in raw_df.iterrows():
        account: str = row[0]
        pairs = _parse_currency_pairs(str(row[1]))

        # Only split if the account holds 2+ distinct currencies.
        distinct_currencies = {curr for curr, _ in pairs}
        if len(distinct_currencies) < 2:
            continue

        # Only split leaf accounts — parents aggregate their children's
        # currencies and should not be split themselves.
        if account in parent_accounts:
            continue

        # Skip if the journal already uses :CURRENCY sub-accounts.
        if any(f"{account}:{curr}" in all_accounts for curr in distinct_currencies):
            continue

        # Skip if this account isn't in valued_df (e.g. filtered out).
        if account not in all_accounts:
            continue

        accounts_to_zero.append(account)
        for curr, amount in pairs:
            rate = rates.get(curr, 1.0)
            converted = amount * rate if curr != disp_currency else amount
            new_rows.append({0: f"{account}:{curr}", 1: converted})

    if not new_rows:
        return valued_df

    result = valued_df.copy()
    # Zero out the original rows — they become parent nodes whose value
    # will be recomputed as the sum of their new currency children by
    # _fix_parent_child_sums in the treemap / Sankey code.
    result.loc[result[0].isin(accounts_to_zero), 1] = 0.0
    # Append the per-currency rows.
    new_df = pd.DataFrame(new_rows)
    result = pd.concat([result, new_df], ignore_index=True)
    return result


@typechecked
def read_balance_report(
    args: Namespace,
    top_level_account_categories: List[str],
    time_period: TimePeriod,
    is_net_worth: Optional[bool] = False,
) -> DataFrame:
    disp_currency: str = args.display_currency
    optional_balance_args = [
        # not:desc:opening: Excludes entries with descriptions containing the
        # word 'opening'.
        # If you only want the balance (changes) of this year, you want to
        # exclude opening statements because they carry over values from assets
        # of previous years.
        "not:desc:opening",
    ]

    if is_net_worth and not time_period.all_time:
        hledger_command: str = build_hledger_command_from_earliest_to_period(
            filename=time_period.filename,
            account_categories=time_period.account_categories,
            time_period=time_period,
            years_and_months=time_period.years_and_months,
            required_exotic_args=time_period.required_exotic_args,
        )
        raw_hledger_command: str = build_hledger_command_from_earliest_to_period(
            filename=time_period.filename,
            account_categories=time_period.account_categories,
            time_period=time_period,
            years_and_months=time_period.years_and_months,
            required_exotic_args=time_period.raw_exotic_args,
        )
    else:
        hledger_command: str = time_period.hledger_command
        raw_hledger_command: str = time_period.raw_hledger_command
    print(f"hledger_command={hledger_command}")

    # Call hledger to compute balances.
    if args.verbose:
        print(f"Ignoring options:{optional_balance_args}\n")
        print(f"default_command=:{hledger_command}\n")

    # 1. Run the valued command (converts everything to display currency).
    valued_df = _run_hledger_to_df(hledger_command, top_level_account_categories)
    valued_df = process_df(df=valued_df, disp_currency=disp_currency)

    # 2. Run the raw command (preserves multi-currency amounts).
    raw_df = _run_hledger_to_df(raw_hledger_command, top_level_account_categories)

    # 3. Split multi-currency accounts into virtual :CURRENCY sub-accounts.
    rates = _get_rates(disp_currency)
    valued_df = _expand_multicurrency_rows(
        raw_df=raw_df,
        valued_df=valued_df,
        disp_currency=disp_currency,
        rates=rates,
    )

    return valued_df


def process_df(*, df, disp_currency):
    rates = _get_rates(disp_currency)

    def parse_convert_and_sum(s, base_currency, rates):
        pairs = _parse_currency_pairs(s)
        total = 0.0
        for curr, value in pairs:
            rate = rates.get(curr, 1.0)
            if curr != base_currency:
                value *= rate
            total += value
        return total

    # Apply to column: first convert to base, sum per row
    df[1] = df[1].apply(
        lambda s: parse_convert_and_sum(s, disp_currency, rates)
    )

    return df

import re
import shlex
import subprocess  # nosec
from argparse import Namespace
from io import StringIO
from typing import List, Optional

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
    else:
        hledger_command: str = time_period.hledger_command
    print(f"hledger_command={hledger_command}")

    # Call hledger to compute balances.
    if args.verbose:
        print(f"Ignoring options:{optional_balance_args}\n")
        print(f"default_command=:{hledger_command}\n")

    process_output = subprocess.run(
        shlex.split(hledger_command),  # ← FIX
        stdout=subprocess.PIPE,
        text=True,
    ).stdout

    # Read the process output into a DataFrame, and clean it up, removing
    # headers.
    raw_df: DataFrame = pd.read_csv(StringIO(process_output), header=None)
    df: DataFrame = raw_df[
        raw_df[0].str.contains("|".join(top_level_account_categories))
    ]

    return process_df(df=df, disp_currency=disp_currency)


# Your original code, enhanced
def process_df(*, df, disp_currency):
    # Fetch or load rates (first try load latest, if missing currencies, fetch new)
    rates = load_latest_rates(disp_currency)
    all_currencies = {c.value for c in Currency}  # Based on enums
    missing = all_currencies - set(rates.keys())
    if missing:
        new_rates, _ = fetch_exchange_rates(base_currency=disp_currency)
        rates.update(new_rates)

    # Parse, convert, and sum function
    def parse_convert_and_sum(s, base_currency, rates):
        # Normalize: replace commas in numbers, but keep for parsing
        s = re.sub(r"(\d),(\d)", r"\1.\2", s)  # Comma to dot for decimals
        # Find pairs: currency followed by optional space/sign and number (handles "POUND-165.93", "EUR 16001,25")
        pairs = re.findall(r"([A-Z]{2,})([\s-]*[-+]?\d+(?:\.\d+)?(?:,\d+)?)", s)
        total = 0.0
        for curr, amt_str in pairs:
            # Clean amount
            amt_str = amt_str.strip().replace(",", "")
            try:
                value = float(amt_str)
                rate = rates.get(curr, 1.0)  # Default 1 if unknown
                if curr != base_currency:
                    value *= rate  # Convert to base
                total += value
            except ValueError:
                pass
        return total

    # Apply to column: first convert to base, sum per row
    df[1] = df[1].apply(
        lambda s: parse_convert_and_sum(s, disp_currency, rates)
    )

    # If needed, further conversions afterwards (e.g., to another currency, but here assuming done)
    # Example: if you want to convert the summed total to another currency post-processing
    # other_currency = 'USD'
    # other_rate = fetch_rate(other_currency, disp_currency)  # Implement if needed
    # df[1] = df[1] * other_rate

    return df

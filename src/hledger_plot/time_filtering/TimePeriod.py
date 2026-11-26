from typing import Dict, List, Optional, Set

from hledger_core.Currency import Currency

from hledger_plot.time_filtering.get_available_periods import (
    get_years_and_months_from_hledger,
)


class TimePeriod:

    def __init__(
        self,
        filename: str,
        account_categories: str,
        disp_currency: Currency,
        all_time: bool,
        month: Optional[int],
        year: Optional[int],
        period_label: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        # A view of part of the journal (hledger_plot.views): its asset
        # balances are no positions and may well be negative.
        partial_view: bool = False,
    ) -> None:
        self.filename: str = filename
        self.partial_view: bool = partial_view
        self.account_categories: str = account_categories
        self.disp_currency: Currency = disp_currency
        self.month: Optional[int] = month
        self.year: Optional[int] = year
        self.all_time: bool = all_time
        self._period_label: Optional[str] = period_label
        self._start_date: Optional[str] = start_date
        self._end_date: Optional[str] = end_date

        self.years_and_months: Dict[int, set[int]] = (
            get_years_and_months_from_hledger(filepath=filename)
        )
        self.required_exotic_args: List[str] = (
            [  # TODO: get from config or args.
                " --tree --no-elide",  # Ensures that parent accounts are listed even
                # if they dont have balance changes. Ensures Sankey flows don't have
                # gaps.
                # Not shown in CLI --help, but probably part of the [QUERY] segment:
                f"--cost --value=then,{disp_currency.value} --infer-value",  # Convert
                # everything to a single commodity, e.g. £,$, EUR etc.
            ]
        )
        # Same flags but without --value=then,<currency> so hledger
        # preserves multi-currency amounts per account.
        self.raw_exotic_args: List[str] = [
            " --tree --no-elide",
            "--cost --infer-value",
        ]
        # Net worth is a position, not a flow: value what is held at the end
        # of the period at market prices.  With --cost, a position bought in
        # EUR and sold for USD keeps +EUR and -USD although it holds 0 BTC.
        self.net_worth_exotic_args: List[str] = [
            " --tree --no-elide",
            f"--value=end,{disp_currency.value} --infer-market-prices",
        ]
        # Native quantities, used to split multi-currency accounts.
        self.net_worth_raw_exotic_args: List[str] = [" --tree --no-elide"]

        # Explicit date range mode (used for weekly periods).
        if start_date is not None and end_date is not None:
            period = f"{start_date} to {end_date}"
            exotic = (
                " " + " ".join(self.required_exotic_args)
                if self.required_exotic_args
                else ""
            )
            raw_exotic = (
                " " + " ".join(self.raw_exotic_args)
                if self.raw_exotic_args
                else ""
            )
            self.hledger_command = (
                f"hledger -f {filename} balance {account_categories} "
                f"--no-total --output-format csv -p '{period}'{exotic}"
            )
            self.raw_hledger_command = (
                f"hledger -f {filename} balance {account_categories} "
                f"--no-total --output-format csv -p '{period}'{raw_exotic}"
            )
            return

        if not all_time:
            if year is None:
                if month is None:
                    raise ValueError(
                        "Must specify year and month if you don't want to show"
                        " the data of all years"
                    )
                else:
                    raise NotImplementedError(
                        "Did not yet implement only showing 1 month of each"
                        " year."
                    )
            else:
                if month is None:
                    # Yearly view: whole year.
                    self.hledger_command: str = (
                        build_hledger_command_for_year(
                            filename=filename,
                            account_categories=account_categories,
                            year=year,
                            required_exotic_args=self.required_exotic_args,
                        )
                    )
                    self.raw_hledger_command: str = (
                        build_hledger_command_for_year(
                            filename=filename,
                            account_categories=account_categories,
                            year=year,
                            required_exotic_args=self.raw_exotic_args,
                        )
                    )
                else:
                    self.hledger_command: str = (
                        build_hledger_command_for_period(
                            filename=filename,
                            account_categories=account_categories,
                            month=month,
                            year=year,
                            required_exotic_args=self.required_exotic_args,
                        )
                    )
                    self.raw_hledger_command: str = (
                        build_hledger_command_for_period(
                            filename=filename,
                            account_categories=account_categories,
                            month=month,
                            year=year,
                            required_exotic_args=self.raw_exotic_args,
                        )
                    )

        else:
            self.hledger_command: str = build_hledger_command_all_time(
                filename=filename,
                account_categories=account_categories,
                required_exotic_args=self.required_exotic_args,
            )
            self.raw_hledger_command: str = build_hledger_command_all_time(
                filename=filename,
                account_categories=account_categories,
                required_exotic_args=self.raw_exotic_args,
            )

    def exclusive_end_date(self) -> str:
        """The first day after this period, as an hledger date."""
        if self._end_date is not None:  # Weekly: already exclusive.
            return self._end_date
        if self.year is None:
            raise ValueError("An all-time period has no end date.")
        if self.month is None:  # Whole year.
            return f"{self.year + 1}/1/1"
        if not 1 <= self.month <= 12:
            raise ValueError("Month must be between 1 and 12.")
        if self.month == 12:
            return f"{self.year + 1}/1/1"
        return f"{self.year}/{self.month + 1}/1"

    def get_period(self) -> str:
        if self._period_label:
            return self._period_label
        if self.all_time:
            return "all_time"
        elif self.month is None:
            return f"{self.year}"
        else:
            return f"{self.year}_{self.month:02d}"


def build_hledger_command_all_time(
    *, filename: str, account_categories: str, required_exotic_args: List[str]
) -> str:
    # read_balance_report--cost: Reads cost-related data in the balance report.
    default_command = (
        f"hledger -f {filename} balance {account_categories} --no-total"
        " --output-format csv"
        + " ".join(required_exotic_args)
    )
    return default_command


def build_hledger_command_for_year(
    *,
    filename: str,
    account_categories: str,
    year: int,
    required_exotic_args: Optional[List[str]] = None,
) -> str:
    """Build a hledger balance command for an entire year."""
    if not isinstance(year, int) or year < 0:
        raise ValueError("Year must be a positive integer.")

    period = f"{year}/1/1 to {year + 1}/1/1"

    exotic_args_str = ""
    if required_exotic_args:
        exotic_args_str = " " + " ".join(required_exotic_args)

    return (
        f"hledger -f {filename} balance {account_categories} "
        f"--no-total --output-format csv -p '{period}'{exotic_args_str}"
    )


def build_hledger_command_for_period(
    *,
    filename: str,
    account_categories: str,
    month: int,
    year: int,
    required_exotic_args: Optional[List[str]] = None,
) -> str:
    """Build a hledger balance command with a *stable* date range.

    The period is expressed as  'YYYY/M/1 to YYYY/M/1'  (no leading zeros,
    single-quoted whole expression, **exactly one space** before any
    additional flags).
    """
    # ---- validation -------------------------------------------------
    if not (1 <= month <= 12):
        raise ValueError("Month must be between 1 and 12.")
    if not isinstance(year, int) or year < 0:
        raise ValueError("Year must be a positive integer.")

    # ---- start / end dates (no leading zeros) -----------------------
    start_date = f"{year}/{month}/1"

    next_month = month + 1
    next_year = year
    if next_month > 12:
        next_month = 1
        next_year += 1

    end_date = f"{next_year}/{next_month}/1"

    period = f"{start_date} to {end_date}"

    # ---- exotic args (guarantee exactly ONE leading space) ----------
    exotic_args_str = ""
    if required_exotic_args:
        # prepend a single space, then join the flags
        exotic_args_str = " " + " ".join(required_exotic_args)

    # ---- final command ----------------------------------------------
    command = (
        f"hledger -f {filename} balance {account_categories} "
        f"--no-total --output-format csv -p '{period}'{exotic_args_str}"
    )
    return command


# ----------------------------------------------------------------------
# 2. Helper that only computes the *date range* (no command string)
# ----------------------------------------------------------------------
def build_hledger_command_from_earliest_to_period(
    *,
    filename: str,
    account_categories: str,
    time_period: TimePeriod,
    years_and_months: Dict[int, Set[int]],
    required_exotic_args: Optional[List[str]] = None,
) -> str:
    """
    Build a *single* hledger command that covers the **first month present**
    in ``years_and_months`` up to (and including) ``time_period``, which can
    be a month, a whole year or a week.
    """
    # ---- find earliest month ------------------------------------------------
    all_years = sorted(years_and_months.keys())
    if not all_years:
        raise ValueError("`years_and_months` is empty – no periods available.")

    start_year = all_years[0]
    start_month = min(years_and_months[start_year])

    period = (
        f"{start_year}/{start_month}/1 to {time_period.exclusive_end_date()}"
    )

    # ---- exotic args --------------------------------------------------------
    exotic = (
        (" " + " ".join(required_exotic_args)) if required_exotic_args else ""
    )

    # ---- final command (same shape as the original) -------------------------
    return (
        f"hledger -f {filename} balance {account_categories} "
        f"--no-total --output-format csv -p '{period}'{exotic}"
    )

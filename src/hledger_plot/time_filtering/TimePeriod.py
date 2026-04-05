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
    ) -> None:
        self.filename: str = filename
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
def _make_period_range(
    start_year: int, start_month: int, end_year: int, end_month: int
) -> str:
    """Return the quoted hledger period string for a given start → end month."""
    start_date = f"{start_year}/{start_month}/1"

    next_m, next_y = end_month + 1, end_year
    if next_m > 12:
        next_m, next_y = 1, end_year + 1
    end_date = f"{next_y}/{next_m}/1"
    return f"{start_date} to {end_date}"


def build_hledger_command_from_earliest_to_period(
    *,
    filename: str,
    account_categories: str,
    time_period: TimePeriod,  # object with .year & .month
    years_and_months: Dict[int, Set[int]],
    required_exotic_args: Optional[List[str]] = None,
) -> str:
    """
    Build a *single* hledger command that covers the **first month present**
    in ``years_and_months`` up to (and including) the month of ``time_period``.
    """
    # ---- validate time_period ------------------------------------------------
    if not hasattr(time_period, "year") or not hasattr(time_period, "month"):
        raise TypeError(
            "`time_period` must expose `.year` and `.month` attributes."
        )

    end_year, end_month = time_period.year, time_period.month
    if not (1 <= end_month <= 12):
        raise ValueError("Target month must be between 1 and 12.")
    if (
        end_year not in years_and_months
        or end_month not in years_and_months[end_year]
    ):
        raise ValueError(
            f"Target period {end_year}/{end_month} not in journal."
        )

    # ---- find earliest month ------------------------------------------------
    all_years = sorted(years_and_months.keys())
    if not all_years:
        raise ValueError("`years_and_months` is empty – no periods available.")

    start_year = all_years[0]
    start_month = min(years_and_months[start_year])

    # ---- reuse the original date-range logic --------------------------------
    period = _make_period_range(start_year, start_month, end_year, end_month)

    # ---- exotic args --------------------------------------------------------
    exotic = (
        (" " + " ".join(required_exotic_args)) if required_exotic_args else ""
    )

    # ---- final command (same shape as the original) -------------------------
    return (
        f"hledger -f {filename} balance {account_categories} "
        f"--no-total --output-format csv -p '{period}'{exotic}"
    )

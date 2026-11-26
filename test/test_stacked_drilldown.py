"""The drill-down can stack the transactions of a week or month into one
column, and back.  Runs real hledger on a small invented journal."""

import shutil
from pathlib import Path

import pandas as pd
import pytest

from hledger_plot.create_plots.create_timeseries_plot import (
    create_category_timeseries,
    period_starts,
    period_totals,
    stacked_columns,
)

JOURNAL = """\
2025-01-06 Baker
    expenses:food:bread       EUR3.00
    assets:cash

2025-01-08 Grocer
    expenses:food:fruit       EUR5.00
    assets:cash

2025-01-13 Baker
    expenses:food:bread       EUR2.00
    assets:cash

2025-02-03 Grocer
    expenses:food:fruit       EUR7.00
    assets:cash
"""


def _dates(*days: str) -> pd.Series:
    return pd.Series(pd.to_datetime(list(days)))


def test_weeks_start_on_monday_and_months_on_the_first() -> None:
    dates = _dates("2025-01-08 14:30", "2025-01-12 09:00", "2025-02-28 18:05")

    weeks = period_starts(dates=dates, period="week")
    months = period_starts(dates=dates, period="month")

    assert [d.date().isoformat() for d in weeks] == [
        "2025-01-06",
        "2025-01-06",
        "2025-02-24",
    ]
    assert [d.date().isoformat() for d in months] == [
        "2025-01-01",
        "2025-01-01",
        "2025-02-01",
    ]


def test_weekly_totals_are_labelled_with_their_first_day() -> None:
    daily = pd.Series(
        [3.0, 5.0, 2.0],
        index=pd.to_datetime(["2025-01-06", "2025-01-08", "2025-01-13"]),
    ).resample("D").sum()

    totals = period_totals(daily=daily, frequency="W-MON")

    # pandas' own "W-MON" labels a week with the Monday that ends it, which
    # drew every weekly total a week late.
    assert totals.to_dict() == {
        pd.Timestamp("2025-01-06"): 8.0,
        pd.Timestamp("2025-01-13"): 2.0,
    }


def test_a_column_spans_most_of_its_period() -> None:
    centres, widths = stacked_columns(
        dates=_dates("2025-01-08", "2025-02-03"), period="month"
    )

    assert centres[0] == pd.Timestamp("2025-01-16 12:00")
    assert widths[0] == pytest.approx(31 * 24 * 3600 * 1000 * 0.9)
    assert widths[1] == pytest.approx(28 * 24 * 3600 * 1000 * 0.9)


@pytest.fixture
def journal(tmp_path: Path) -> str:
    if not shutil.which("hledger"):
        pytest.skip("needs hledger")
    path = tmp_path / "food.journal"
    path.write_text(JOURNAL, encoding="utf-8")
    return str(path)


def _bars(figure) -> list:
    return [trace for trace in figure.data if trace.type == "bar"]


def test_one_bar_per_transaction_without_stacking(journal: str) -> None:
    figure = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
    )

    xs = sorted(str(x)[:10] for bar in _bars(figure) for x in bar.x)
    assert xs == ["2025-01-06", "2025-01-08", "2025-01-13", "2025-02-03"]
    assert figure.layout.barmode == "stack"


def test_stacked_per_month_every_transaction_is_a_segment_of_its_month(
    journal: str,
) -> None:
    figure = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
        stack="month",
    )

    segments = sorted(
        (str(pd.Timestamp(x).date()), y)
        for bar in _bars(figure)
        for x, y in zip(bar.x, bar.y)
    )
    assert segments == [
        ("2025-01-16", 2.0),
        ("2025-01-16", 3.0),
        ("2025-01-16", 5.0),
        ("2025-02-15", 7.0),  # 1 February + 14 of its 28 days
    ]
    assert figure.layout.barmode == "relative"
    assert "stacked per month" in figure.layout.title.text


def test_stacked_per_week_shows_the_weekly_average(journal: str) -> None:
    figure = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
        stack="week",
    )
    weekly_avg = next(
        trace for trace in figure.data if trace.name.startswith("Weekly avg")
    )
    unstacked = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
    )

    assert weekly_avg.visible is True
    assert next(
        trace for trace in unstacked.data if trace.name.startswith("Weekly avg")
    ).visible == "legendonly"


def test_the_zoom_stays_but_the_heights_refit_when_stacking(
    journal: str,
) -> None:
    plain = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
    )
    stacked = create_category_timeseries(
        journal_filepath=journal,
        account_prefix="expenses:food",
        display_currency="EUR",
        stack="month",
    )

    assert plain.layout.xaxis.uirevision == stacked.layout.xaxis.uirevision
    assert plain.layout.yaxis.uirevision != stacked.layout.yaxis.uirevision


def test_an_unknown_stack_period_is_refused(journal: str) -> None:
    with pytest.raises(ValueError):
        create_category_timeseries(
            journal_filepath=journal,
            account_prefix="expenses:food",
            display_currency="EUR",
            stack="decade",
        )

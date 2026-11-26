"""Views of the journal: who can see a transaction, and what it was for.

Runs real hledger on a small invented journal.
"""

import shutil
import subprocess
from datetime import date
from pathlib import Path

import pytest

from hledger_plot.views.journal_views import (
    BOTH,
    TRACEABLE,
    UNTRACEABLE,
    JournalViews,
    describe_view,
)
from hledger_plot.views.rules import (
    AccountRule,
    EntryMatcher,
    JournalEntry,
    TraceabilityRules,
    load_traceability_rules,
)

pytestmark = pytest.mark.skipif(
    not shutil.which("hledger"), reason="needs hledger"
)

BANK = "assets:sam:examplebank:checking"
WALLET = "assets:sam:wallet:physical"
EXCHANGE = "assets:sam:coinplace:trading"

JOURNAL = f"""\
2025-01-05 Toolshop  ; workbench:
    expenses:tools          EUR12.75
    {BANK}

2025-01-06 Bakery
    expenses:food            EUR4.50
    {WALLET}

2025-01-07 Market  ; traceable:yes
    expenses:food           EUR12.00
    {WALLET}

2025-02-01 To the exchange
    {EXCHANGE}             EUR100.00
    {BANK}

2025-03-02 Seaside dinner
    expenses:dining         EUR40.00
    {BANK}

2025-03-03 Ice cream  ; trip:
    expenses:food            EUR3.00
    {WALLET}
"""


def _entry(**kwargs) -> JournalEntry:
    fields = dict(
        date=date(2025, 1, 5),
        description="Toolshop",
        tags=(),
        accounts=("expenses:tools", BANK),
        amounts=(12.75, -12.75),
    )
    fields.update(kwargs)
    return JournalEntry(**fields)


def test_accounts_from_a_bank_csv_are_traceable_by_default() -> None:
    rules = TraceabilityRules(default_traceable=(BANK,))

    assert rules.entry_traceable(entry=_entry())
    assert not rules.entry_traceable(
        entry=_entry(accounts=("expenses:food", WALLET))
    )


def test_account_rules_can_change_over_time() -> None:
    until_2024 = AccountRule(
        account=EXCHANGE, traceable=False, end=date(2024, 12, 31)
    )
    since_2025 = AccountRule(
        account=EXCHANGE, traceable=True, start=date(2025, 1, 1)
    )
    rules = TraceabilityRules(accounts=(until_2024, since_2025))

    assert not rules.account_traceable(account=EXCHANGE, day=date(2024, 6, 1))
    assert rules.account_traceable(account=EXCHANGE, day=date(2025, 6, 1))
    assert rules.account_traceable(
        account=EXCHANGE + ":sub", day=date(2025, 6, 1)
    )
    assert not rules.account_traceable(
        account=EXCHANGE + "x", day=date(2025, 6, 1)
    )


def test_the_receipts_say_beats_the_accounts_and_a_rule_beats_both() -> None:
    marked = _entry(
        tags=(("traceable", "no"),), accounts=("expenses:tools", BANK)
    )
    rules = TraceabilityRules(default_traceable=(BANK,))
    assert not rules.entry_traceable(entry=marked)

    override = TraceabilityRules(
        default_traceable=(BANK,),
        transactions=((EntryMatcher(description="toolshop"), True),),
    )
    assert override.entry_traceable(entry=marked)


def test_matcher_conditions_all_have_to_hold() -> None:
    entry = _entry()

    assert EntryMatcher(amount=12.75, account="expenses").matches(entry=entry)
    assert not EntryMatcher(amount=13.5).matches(entry=entry)
    assert not EntryMatcher(start=date(2025, 2, 1)).matches(entry=entry)
    assert not EntryMatcher(description="^shop").matches(entry=entry)


def test_rules_file(tmp_path: Path) -> None:
    path = tmp_path / "traceability.yaml"
    path.write_text(
        "accounts:\n"
        f"  - account: {WALLET}\n"
        "    traceable: true\n"
        "    from: 2025-01-07\n"
        "transactions:\n"
        "  - date: 2025-01-05\n"
        "    description: Toolshop\n"
        "    traceable: false\n",
        encoding="utf-8",
    )

    rules = load_traceability_rules(path=str(path), default_traceable=[BANK])

    assert rules.accounts[0].start == date(2025, 1, 7)
    assert not rules.entry_traceable(entry=_entry())
    assert rules.default_traceable == (BANK,)


@pytest.mark.parametrize(
    "content",
    [
        "accounts:\n  - traceable: true\n",
        f"accounts:\n  - account: {BANK}\n    traceable: maybe\n",
        "transactions:\n  - description: '('\n    traceable: true\n",
        "- just a list\n",
    ],
)
def test_a_wrong_rules_file_is_refused(tmp_path: Path, content: str) -> None:
    path = tmp_path / "traceability.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError):
        load_traceability_rules(path=str(path))


@pytest.fixture
def views(tmp_path: Path) -> JournalViews:
    root = tmp_path / "finance"
    root.mkdir()
    journal = root / "all.journal"
    journal.write_text(JOURNAL, encoding="utf-8")
    (root / "tags.yaml").write_text(
        "trip:\n"
        "  description: A week by the sea\n"
        "  from: 2025-03-01\n"
        "  to: 2025-03-05\n"
        "  rules:\n"
        f"    - account: {BANK}\n"
        "      from: 2025-03-01\n"
        "      to: 2025-03-05\n"
        "workbench:\n",
        encoding="utf-8",
    )
    return JournalViews(
        journal_filepath=str(journal),
        cache_dir=str(tmp_path / "views"),
        root_finance_path=str(root),
        default_traceable=[BANK],
    )


def _descriptions(views: JournalViews, **choice) -> list:
    return [entry.description for entry in views.selected(**choice)]


def test_traceable_and_untraceable_split_the_journal(views) -> None:
    assert _descriptions(views, traceability=TRACEABLE, tag=None) == [
        "Toolshop",
        "Market",
        "To the exchange",
        "Seaside dinner",
    ]
    assert _descriptions(views, traceability=UNTRACEABLE, tag=None) == [
        "Bakery",
        "Ice cream",
    ]
    assert len(views.selected(traceability=BOTH, tag=None)) == 6


def test_a_tag_view_has_the_tagged_and_the_matching_transactions(views):
    assert _descriptions(views, traceability=BOTH, tag="trip") == [
        "Seaside dinner",
        "Ice cream",
    ]
    assert _descriptions(views, traceability=UNTRACEABLE, tag="trip") == [
        "Ice cream"
    ]
    assert views.tag_names() == ["trip", "workbench"]


def test_a_view_journal_is_read_by_hledger(views) -> None:
    path = views.journal_for(traceability=UNTRACEABLE, tag=None)

    printed = subprocess.run(
        ["hledger", "-f", path, "print"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert "Bakery" in printed and "Ice cream" in printed
    assert "Toolshop" not in printed
    assert views.journal_for(traceability=BOTH, tag=None) == (
        views.journal_filepath
    )


def test_tag_costs(views) -> None:
    costs = {cost.tag: cost for cost in views.tag_costs(
        traceability=BOTH, display_currency="EUR"
    )}

    assert costs["trip"].cost == pytest.approx(43.0)
    assert costs["trip"].transactions == 2
    assert costs["trip"].description == "A week by the sea"
    assert costs["workbench"].cost == pytest.approx(12.75)


def test_an_edited_rules_file_counts_at_once(views, tmp_path: Path) -> None:
    (tmp_path / "finance" / "traceability.yaml").write_text(
        f"accounts:\n  - account: {WALLET}\n    traceable: true\n",
        encoding="utf-8",
    )

    assert _descriptions(views, traceability=UNTRACEABLE, tag=None) == []


def test_describe_view() -> None:
    assert describe_view(traceability=BOTH, tag=None) == ""
    assert describe_view(traceability=TRACEABLE, tag="workbench") == (
        "only transactions others can trace; only tag workbench"
    )

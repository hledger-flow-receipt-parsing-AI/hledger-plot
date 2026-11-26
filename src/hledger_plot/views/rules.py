"""Who can see a transaction (traceability) and what it was for (tags).

traceability.yaml in the finance root (every key optional):

    # Accounts: a transaction is traceable when one of its accounts is
    # traceable on its date.  Later rules win.  Accounts no rule names are
    # traceable when they come from a bank CSV (config.yaml), else not.
    accounts:
      - account: assets:sam:wallet        # this account and those below it
        traceable: false
      - account: assets:sam:coinplace
        traceable: false
        until: 2024-12-31
      - account: assets:sam:coinplace      # traceable since the KYC check
        traceable: true
        from: 2025-01-01
    # Single transactions, whatever their accounts and receipt say.
    transactions:
      - date: 2025-06-07
        description: Toolshop             # a regular expression, any case
        amount: 9.95
        traceable: false

A receipt's own say ("traceable"/"untraceable" while labelling, or paid by
card and cash) arrives as the journal tag traceable:yes/no and beats the
account rules; the transactions above beat everything.

tags.yaml (hledger_core.tagging) may give a tag rules in the same form as
the transactions above (without "traceable"): matching transactions get
the tag too, e.g. every bank payment during a holiday.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml
from hledger_core.tagging import TagDefinition, as_date
from typeguard import typechecked

TRACEABILITY_FILENAME = "traceability.yaml"


@typechecked
@dataclass(frozen=True)
class JournalEntry:
    """One transaction of the journal, as far as the views need it."""

    date: date
    description: str
    tags: Tuple[Tuple[str, str], ...]
    accounts: Tuple[str, ...]
    amounts: Tuple[float, ...]
    # The entry as ``hledger print`` writes it.
    text: str = ""

    def tag_value(self, *, name: str) -> Optional[str]:
        values = [value for tag, value in self.tags if tag == name]
        return values[-1] if values else None


@typechecked
def under(*, account: str, prefix: str) -> bool:
    """*account* is *prefix* or an account below it."""
    return account == prefix or account.startswith(prefix + ":")


@typechecked
@dataclass(frozen=True)
class EntryMatcher:
    """Conditions on a transaction; every condition given must hold."""

    start: Optional[date] = None
    end: Optional[date] = None
    account: Optional[str] = None
    description: Optional[str] = None
    amount: Optional[float] = None

    def matches(self, *, entry: JournalEntry) -> bool:
        if self.start is not None and entry.date < self.start:
            return False
        if self.end is not None and entry.date > self.end:
            return False
        if self.account is not None and not any(
            under(account=account, prefix=self.account)
            for account in entry.accounts
        ):
            return False
        if self.description is not None and not re.search(
            self.description, entry.description, re.IGNORECASE
        ):
            return False
        if self.amount is not None and not any(
            abs(abs(amount) - self.amount) < 0.005 for amount in entry.amounts
        ):
            return False
        return True


@typechecked
def matcher_from(*, raw: Dict[str, Any], where: str) -> EntryMatcher:
    """An EntryMatcher from a rule of a rules file ("date" is one day,
    "from"/"until" (or "to") a period)."""
    day = as_date(value=raw.get("date"), what=where)
    start = as_date(value=raw.get("from"), what=where)
    end = as_date(value=raw.get("until", raw.get("to")), what=where)
    if day is not None:
        start = end = day
    description = raw.get("description")
    if description is not None:
        try:
            re.compile(str(description))
        except re.error as error:
            raise ValueError(f"{where}: description: {error}") from error
    amount = raw.get("amount")
    return EntryMatcher(
        start=start,
        end=end,
        account=str(raw["account"]) if raw.get("account") else None,
        description=str(description) if description is not None else None,
        amount=float(amount) if amount is not None else None,
    )


@typechecked
@dataclass(frozen=True)
class AccountRule:
    account: str
    traceable: bool
    start: Optional[date] = None
    end: Optional[date] = None

    def applies(self, *, account: str, day: date) -> bool:
        if not under(account=account, prefix=self.account):
            return False
        if self.start is not None and day < self.start:
            return False
        if self.end is not None and day > self.end:
            return False
        return True


@typechecked
@dataclass(frozen=True)
class TraceabilityRules:
    accounts: Tuple[AccountRule, ...] = ()
    transactions: Tuple[Tuple[EntryMatcher, bool], ...] = ()
    # Accounts that are traceable when no rule names them: the bank CSVs.
    default_traceable: Tuple[str, ...] = field(default_factory=tuple)

    def account_traceable(self, *, account: str, day: date) -> bool:
        decision: Optional[bool] = None
        for rule in self.accounts:
            if rule.applies(account=account, day=day):
                decision = rule.traceable
        if decision is None:
            decision = any(
                under(account=account, prefix=prefix)
                for prefix in self.default_traceable
            )
        return decision

    def entry_traceable(self, *, entry: JournalEntry) -> bool:
        decision: Optional[bool] = None
        for matcher, traceable in self.transactions:
            if matcher.matches(entry=entry):
                decision = traceable
        if decision is not None:
            return decision
        tagged = entry.tag_value(name="traceable")
        if tagged is not None and tagged.strip().lower() in ("yes", "no"):
            return tagged.strip().lower() == "yes"
        return any(
            self.account_traceable(account=account, day=entry.date)
            for account in entry.accounts
        )


@typechecked
def _flag(*, value: Any, where: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{where}: traceable must be true or false")


@typechecked
def load_traceability_rules(
    *, path: str, default_traceable: Sequence[str] = ()
) -> TraceabilityRules:
    """The rules in *path* (none when it does not exist)."""
    content: Any = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            content = yaml.safe_load(handle) or {}
        if not isinstance(content, dict):
            raise ValueError(f"{path}: expected 'accounts' and 'transactions'")
    accounts: List[AccountRule] = []
    for index, raw in enumerate(content.get("accounts") or []):
        where = f"{path}: accounts[{index}]"
        if not isinstance(raw, dict) or not raw.get("account"):
            raise ValueError(f"{where}: needs an account")
        accounts.append(
            AccountRule(
                account=str(raw["account"]),
                traceable=_flag(value=raw.get("traceable"), where=where),
                start=as_date(value=raw.get("from"), what=where),
                end=as_date(value=raw.get("until", raw.get("to")), what=where),
            )
        )
    transactions: List[Tuple[EntryMatcher, bool]] = []
    for index, raw in enumerate(content.get("transactions") or []):
        where = f"{path}: transactions[{index}]"
        if not isinstance(raw, dict):
            raise ValueError(f"{where}: expected conditions")
        transactions.append(
            (
                matcher_from(raw=raw, where=where),
                _flag(value=raw.get("traceable"), where=where),
            )
        )
    return TraceabilityRules(
        accounts=tuple(accounts),
        transactions=tuple(transactions),
        default_traceable=tuple(default_traceable),
    )


# Tags that are no event or project: the traceability tag, and hledger's
# hidden tags (they start with "_").
NOT_USER_TAGS = ("traceable",)


@typechecked
class TagRules:
    """The tags of a journal entry: its own (from its receipt) and those
    of tags.yaml whose rules match it."""

    def __init__(self, *, definitions: Iterable[TagDefinition]) -> None:
        self.definitions: List[TagDefinition] = list(definitions)
        self._rules: List[Tuple[str, EntryMatcher]] = [
            (
                definition.name,
                matcher_from(raw=raw, where=f"tags.yaml: {definition.name}"),
            )
            for definition in self.definitions
            for raw in definition.rules
        ]

    def entry_tags(self, *, entry: JournalEntry) -> List[str]:
        tags: List[str] = []
        for name, _ in entry.tags:
            if name.startswith("_") or name in NOT_USER_TAGS:
                continue
            if name not in tags:
                tags.append(name)
        for name, matcher in self._rules:
            if name not in tags and matcher.matches(entry=entry):
                tags.append(name)
        return tags

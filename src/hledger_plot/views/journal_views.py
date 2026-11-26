"""Views of the journal: all transactions, only the traceable ones or only
the others, optionally only those of one tag (an event or project).

A view is a journal file with the chosen transactions (as ``hledger print``
writes them) and every market price of the full journal, so amounts are
valued the same in every view.  The plots read it like the full journal.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess  # nosec
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Sequence

from hledger_core.tagging import load_tag_definitions, tags_file_path
from typeguard import typechecked

from hledger_plot.views.rules import (
    TRACEABILITY_FILENAME,
    JournalEntry,
    TagRules,
    TraceabilityRules,
    load_traceability_rules,
)

BOTH = "both"
TRACEABLE = "traceable"
UNTRACEABLE = "untraceable"
TRACEABILITY_CHOICES = (BOTH, TRACEABLE, UNTRACEABLE)


@typechecked
def _hledger(*, journal_filepath: str, arguments: Sequence[str]) -> str:
    return subprocess.run(  # nosec
        ["hledger", "-f", journal_filepath, *arguments],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@typechecked
def read_entries(*, journal_filepath: str) -> List[JournalEntry]:
    """Every transaction of the journal, in ``hledger print`` order."""
    data = json.loads(
        _hledger(
            journal_filepath=journal_filepath, arguments=["print", "-O", "json"]
        )
    )
    printed = [
        block
        for block in _hledger(
            journal_filepath=journal_filepath, arguments=["print"]
        ).split("\n\n")
        if block.strip()
    ]
    if len(printed) != len(data):
        raise RuntimeError(
            "hledger print gave a different number of transactions as text"
            f" ({len(printed)}) and as JSON ({len(data)})"
        )
    entries: List[JournalEntry] = []
    for transaction, text in zip(data, printed):
        postings = transaction.get("tpostings") or []
        entries.append(
            JournalEntry(
                date=date.fromisoformat(transaction["tdate"]),
                description=transaction.get("tdescription") or "",
                tags=tuple(
                    (str(name), str(value))
                    for name, value in transaction.get("ttags") or []
                ),
                accounts=tuple(p["paccount"] for p in postings),
                amounts=tuple(
                    float(amount["aquantity"]["floatingPoint"])
                    for p in postings
                    for amount in p.get("pamount") or []
                ),
                text=text.strip("\n"),
            )
        )
    return entries


@typechecked
def default_traceable_accounts(*, config: Any) -> List[str]:
    """The hledger names of the accounts read from a bank (or exchange)
    CSV: others keep a record of their transactions."""
    return [
        f"assets:{account_config.account.to_string()}"
        for account_config in getattr(config, "accounts", None) or []
        if account_config.has_input_csv()
    ]


@typechecked
@dataclass(frozen=True)
class TagCost:
    tag: str
    description: str
    # In the display currency.
    cost: float
    transactions: int
    # Amounts without a price in the display currency, per commodity.
    unconverted: Dict[str, float]


class JournalViews:
    """Builds (and keeps) the view journals of one journal."""

    @typechecked
    def __init__(
        self,
        *,
        journal_filepath: str,
        cache_dir: str,
        root_finance_path: Optional[str],
        default_traceable: Sequence[str] = (),
    ) -> None:
        self.journal_filepath = journal_filepath
        self.cache_dir = cache_dir
        self.root_finance_path = root_finance_path
        self.default_traceable = tuple(default_traceable)
        self._entries: Optional[List[JournalEntry]] = None
        self._prices: Optional[str] = None

    # -- inputs ---------------------------------------------------------
    def _rules_path(self, *, name: str) -> Optional[str]:
        if self.root_finance_path is None:
            return None
        return os.path.join(self.root_finance_path, name)

    def entries(self) -> List[JournalEntry]:
        if self._entries is None:
            self._entries = read_entries(journal_filepath=self.journal_filepath)
        return self._entries

    def traceability_rules(self) -> TraceabilityRules:
        """Read on every use, so an edited traceability.yaml counts at the
        next click."""
        path = self._rules_path(name=TRACEABILITY_FILENAME)
        if path is None:
            return TraceabilityRules(default_traceable=self.default_traceable)
        return load_traceability_rules(
            path=path, default_traceable=self.default_traceable
        )

    def tag_rules(self) -> TagRules:
        if self.root_finance_path is None:
            return TagRules(definitions=[])
        return TagRules(
            definitions=load_tag_definitions(
                path=tags_file_path(root_finance_path=self.root_finance_path)
            )
        )

    # -- selections -----------------------------------------------------
    @typechecked
    def selected(
        self, *, traceability: str, tag: Optional[str]
    ) -> List[JournalEntry]:
        if traceability not in TRACEABILITY_CHOICES:
            raise ValueError(f"Unknown traceability view: {traceability}")
        rules = self.traceability_rules()
        tags = self.tag_rules()
        chosen: List[JournalEntry] = []
        for entry in self.entries():
            if traceability != BOTH:
                traceable = rules.entry_traceable(entry=entry)
                if traceable != (traceability == TRACEABLE):
                    continue
            if tag is not None and tag not in tags.entry_tags(entry=entry):
                continue
            chosen.append(entry)
        return chosen

    def _market_prices(self) -> str:
        """P directives for every price of the full journal, also those
        inferred from costs, so a view values amounts like the whole."""
        if self._prices is None:
            self._prices = _hledger(
                journal_filepath=self.journal_filepath,
                arguments=["prices", "--infer-market-prices"],
            )
        return self._prices

    @typechecked
    def journal_for(self, *, traceability: str, tag: Optional[str]) -> str:
        """The journal file of the view (the journal itself for all
        transactions without a tag)."""
        if traceability == BOTH and tag is None:
            return self.journal_filepath
        entries = self.selected(traceability=traceability, tag=tag)
        content = (
            f"; hledger_plot view of {self.journal_filepath}:"
            f" {traceability}, tag {tag or '-'}\n\n"
            + self._market_prices()
            + "\n"
            + "\n\n".join(entry.text for entry in entries)
            + "\n"
        )
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        os.makedirs(self.cache_dir, exist_ok=True)
        path = os.path.join(self.cache_dir, f"view_{digest}.journal")
        if not os.path.isfile(path):
            temporary = path + ".tmp"
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(content)
            os.replace(temporary, path)
        return path

    # -- tags -----------------------------------------------------------
    def tag_names(self) -> List[str]:
        """Every tag of tags.yaml and of the journal, tags.yaml first."""
        rules = self.tag_rules()
        names = [definition.name for definition in rules.definitions]
        for entry in self.entries():
            for name in rules.entry_tags(entry=entry):
                if name not in names:
                    names.append(name)
        return names

    @typechecked
    def tag_costs(
        self, *, traceability: str, display_currency: str
    ) -> List[TagCost]:
        """What every tag cost (its expenses, all time), most first."""
        descriptions: Dict[str, str] = {
            definition.name: definition.description
            for definition in self.tag_rules().definitions
        }
        costs: List[TagCost] = []
        for name in self.tag_names():
            entries = self.selected(traceability=traceability, tag=name)
            if not entries:
                continue
            journal = self.journal_for(traceability=traceability, tag=name)
            totals = expenses_total(
                journal_filepath=journal, display_currency=display_currency
            )
            costs.append(
                TagCost(
                    tag=name,
                    description=descriptions.get(name, ""),
                    cost=totals.pop(display_currency, 0.0),
                    transactions=len(entries),
                    unconverted={
                        commodity or "?": value
                        for commodity, value in totals.items()
                        if abs(value) > 0.005
                    },
                )
            )
        return sorted(costs, key=lambda cost: -cost.cost)


@typechecked
def expenses_total(
    *, journal_filepath: str, display_currency: str
) -> Dict[str, float]:
    """The expenses of *journal_filepath* per commodity, valued in
    *display_currency* on the day of each transaction (as the treemaps
    do); what has no price stays in its own commodity."""
    data = json.loads(
        _hledger(
            journal_filepath=journal_filepath,
            arguments=[
                "balance",
                "^expenses",
                "--depth",
                "1",
                "--cost",
                f"--value=then,{display_currency}",
                "--infer-market-prices",
                "--output-format",
                "json",
            ],
        )
    )
    totals: Dict[str, float] = {}
    for amount in data[1] if len(data) > 1 else []:
        commodity = amount.get("acommodity") or ""
        totals[commodity] = totals.get(commodity, 0.0) + float(
            amount["aquantity"]["floatingPoint"]
        )
    return totals


@typechecked
def describe_view(*, traceability: str, tag: Optional[str]) -> str:
    """A short caption of the view for above the plots."""
    parts: List[str] = []
    if traceability == TRACEABLE:
        parts.append("only transactions others can trace")
    elif traceability == UNTRACEABLE:
        parts.append("only transactions others cannot trace")
    if tag is not None:
        parts.append(f"only tag {tag}")
    return "; ".join(parts)


@typechecked
def tag_options(*, names: Sequence[str]) -> List[Dict[str, str]]:
    return [{"label": name, "value": name} for name in names]

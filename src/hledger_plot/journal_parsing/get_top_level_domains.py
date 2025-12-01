import io
import os
from typing import List

from typeguard import typechecked

from hledger_plot.file_reading_and_writing import load_file_to_string
from hledger_plot.journal_parsing.import_journal_file import (
    Transaction,
    parseJournal,
)


@typechecked
def get_top_level_account_categories(*, journal_filepath: str) -> List[str]:
    transactions: List[Transaction] = get_all_transactions_from_journal(
        journal_filepath=journal_filepath
    )
    top_level_account_category_account_categories: List[str] = (
        get_top_level_account_category_domains_from_transactions(
            transactions=transactions
        )
    )
    return top_level_account_category_account_categories


@typechecked
def get_top_level_account_category_domains_from_transactions(
    *, transactions: List[Transaction]
) -> List[str]:

    top_level_account_category_account_categories: List[str] = []
    for transaction in transactions:
        for posting in transaction.postings:
            top_level_account_category: str = posting.account.strip().split(
                ":"
            )[0]
            if (
                top_level_account_category
                not in top_level_account_category_account_categories
            ):
                top_level_account_category_account_categories.append(
                    top_level_account_category
                )
    return top_level_account_category_account_categories


@typechecked
def get_all_transactions_from_journal(
    *, journal_filepath: str
) -> List[Transaction]:

    parent_path: str = os.path.dirname(journal_filepath)
    journal_content: str = load_file_to_string(filepath=journal_filepath)
    test_journal1 = io.StringIO(journal_content)
    j: List[Transaction] = parseJournal(
        jreader=test_journal1, parent_path=parent_path
    )
    return j

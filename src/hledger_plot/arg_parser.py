"""Parses the CLI args."""

import argparse
import re
from argparse import ArgumentParser
from typing import Any

from typeguard import typechecked


@typechecked
def create_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Triodos Bank CSV to custom format."
    )

    # Hledger configuration/usage parameters.
    parser.add_argument(
        "-ac",
        "--asset-categories",
        type=str,
        required=False,
        help=(
            "(Default/empty=assets). Override top level asset category(s) in"
            " csv format like:assets,poetry"
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        type=str,
        required=False,
        help="Path to config file.",
    )

    parser.add_argument(
        "-ec",
        "--expense-categories",
        type=str,
        required=False,
        help=(
            "(Default/empty=expenses).Override top level expense category(s)"
            " in csv format like:expenses,depreciation"
        ),
    )
    parser.add_argument(
        "-lc",
        "--liability-categories",
        type=str,
        required=False,
        help=(
            "(Default/empty=liabilities).Override top level liability"
            " category(s) in csv format like:liabilities,caused_entropy"
        ),
    )
    parser.add_argument(
        "-ic",
        "--income-categories",
        type=str,
        required=False,
        help=(
            "(Default/empty=income).Override top level income category(s) in"
            " csv format like:income,revenue"
        ),
    )
    parser.add_argument(
        "--equity-categories",
        type=str,
        required=False,
        help=(
            "(Default/empty=equity).Override top level equity category(s) in"
            " csv format like:equity,horsemanity"
        ),
    )
    parser.add_argument(
        "-p",
        "--start-path",
        type=str,
        required=False,
        help="Path to root of the finance repo/folder.",
    )

    # Input arguments.
    parser.add_argument(
        "-j",
        "--journal-filepath",
        type=str,
        help="Specify the path to the input journal file.",
    )
    # Where to find the relevant data if no input file is given.
    parser.add_argument(
        "-a",
        "--account-holder",
        type=str,
        required=False,
        help="Name of account holder.",
    )
    parser.add_argument(
        "-b", "--bank", type=str, required=False, help="Name of bank."
    )
    parser.add_argument(
        "-t",
        "--account-type",
        type=str,
        required=False,
        help="Account type, e.g. checkings/savings etc..",
    )

    # Output arguments
    parser.add_argument(
        "-et",
        "--export-treemap",
        action="store_true",
        help="Export treemap to file.",
    )
    parser.add_argument(
        "-es",
        "--export-sankey",
        action="store_true",
        help="Export Sankey diagram to file.",
    )
    parser.add_argument(
        "-s",
        "--show-plots",
        action="store_true",
        help="Show 2 Sankey diagrams and 1 treemap plot.",
    )
    parser.add_argument(
        "-d",
        "--display-currency",
        type=str,
        required=False,
        help=(
            "Currency in which you want to show your transatctions, e.g. EUR, $"
            " etc.."
        ),
    )
    parser.add_argument(
        "-r",
        "--randomize",
        action="store_true",
        help="Obvuscates data for demo purposes using randomization.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        required=False,
        help="Print intermediate information.",
    )

    return parser


@typechecked
def verify_args(*, parser: ArgumentParser) -> Any:
    args: Any = parser.parse_args()
    if args.account_holder or args.bank or args.account_type:
        if not args.account_holder or not args.bank or not args.account_type:
            raise ValueError(
                "If you specify the account holder, bank, or account type, you"
                " should specify them all."
            )
        if not args.start_path:
            raise ValueError(
                "If you specify the account holder, bank, or account type, you"
                " should include the start path to your finance dir that"
                " contains the /import directory."
            )
        assert_has_only_valid_chars(input_string=args.account_holder)
        assert_has_only_valid_chars(input_string=args.bank)
        assert_has_only_valid_chars(input_string=args.account_type)
    if args.journal_filepath:
        if (
            args.account_holder
            or args.bank
            or args.account_type
            or args.start_path
        ):
            raise ValueError(
                "You gave a journal filepath and account_holder/bankPlesase do"
                " 1 thing at a time."
            )

    return args


@typechecked
def assert_has_only_valid_chars(*, input_string: str) -> None:
    # a-Z, underscore, \, /.
    valid_chars = re.compile(r"^[a-zA-Z0-9_/\\]*$")
    if not valid_chars.match(input_string):
        raise ValueError(f"Invalid characters found in: {input_string}")

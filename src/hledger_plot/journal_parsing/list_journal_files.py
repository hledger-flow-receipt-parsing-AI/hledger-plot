import os
import shlex
import subprocess
from typing import List

from hledger_core.generics.hashing import hash_something


def list_journal_files(*, abs_journal_root_filepath: str) -> List[str]:
    """
    Returns a list of absolute file paths from `hledger files`.
    Asserts all files exist.
    """
    list_all_files_cmd = (
        f"hledger -f {shlex.quote(abs_journal_root_filepath)} files"
    )

    try:
        result = subprocess.run(
            shlex.split(list_all_files_cmd),
            capture_output=True,
            text=True,
            check=True,
            cwd="/",
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"hledger command failed: {e.stderr.strip()}") from e

    # Parse stdout into list of filepaths
    raw_files = result.stdout.strip().split("\n")
    filepaths = [line.strip() for line in raw_files if line.strip()]

    # Resolve to absolute paths and validate existence
    validated_files: List[str] = []
    for fp in filepaths:
        abs_fp = os.path.abspath(fp)
        if not os.path.isfile(abs_fp):
            raise FileNotFoundError(f"Journal file not found: {abs_fp}")
        validated_files.append(abs_fp)

    return validated_files


def load_and_hash_journal_files(
    *, abs_journal_root_filepath: str
) -> tuple[List[str], str]:
    """
    1. Gets list of journal files via hledger
    2. Loads each file's content
    3. Concatenates contents (in hledger order)
    4. Returns (list_of_filepaths, combined_content_hash)
    """
    filepaths = list_journal_files(
        abs_journal_root_filepath=abs_journal_root_filepath
    )

    contents: List[str] = []
    for fp in filepaths:
        try:
            with open(fp, encoding="utf-8") as f:
                contents.append(f.read())
        except Exception as e:
            raise RuntimeError(f"Failed to read file {fp}: {e}") from e

    # Concatenate all file contents in order (no separators, as per your spec)
    combined_content = "".join(contents)

    # Generate hash of the combined content
    content_hash = hash_something(something=combined_content)
    return filepaths, content_hash

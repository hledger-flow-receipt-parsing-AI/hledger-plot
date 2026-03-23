import shlex
import shutil
import subprocess
from collections import defaultdict

# hledger -f {filename} dates --output-format "%Y-%m-%d"
from typing import Dict, Set

from typeguard import typechecked  # or @typechecked if using typeguard


@typechecked
def get_years_and_months_from_hledger(*, filepath: str) -> Dict[int, Set[int]]:
    """
    Runs `hledger register` and extracts years and months from the transaction dates.
    Returns: {year: {month1, month2, ...}}
    """
    cmd = f"hledger -f {shlex.quote(filepath)} register"
    print("hledger path:", shutil.which("hledger"))
    print(
        "hledger version:",
        subprocess.run(
            ["hledger", "--version"], capture_output=True, text=True
        ).stdout.strip(),
    )

    try:
        result = subprocess.run(
            shlex.split(cmd), capture_output=True, text=True, check=True,
            cwd="/",
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"hledger command failed: {e.stderr.strip()}") from e

    year_to_months: Dict[int, Set[int]] = defaultdict(set)

    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or not line[0].isdigit():
            continue
        try:
            date_part = line.split()[0]
            year_str, month_str, *_ = date_part.split("-")
            year = int(year_str)
            month = int(month_str)
            if 1 <= month <= 12:
                year_to_months[year].add(month)
        except Exception:
            continue

    return dict(sorted(year_to_months.items()))

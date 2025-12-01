import os
import random
from typing import Dict, List, Tuple, Union

import pandas as pd
from pandas.core.series import Series
from typeguard import typechecked

from hledger_plot.random_categories import long_random_categories

# vulture
pd.options.mode.copy_on_write = True


@typechecked
def get_rand_categories(*, random_wordlist_filepath: str) -> List[str]:

    if os.path.exists(random_wordlist_filepath):
        return load_words_from_file(filepath=random_wordlist_filepath)

    return sorted(long_random_categories)


@typechecked
def load_words_from_file(*, filepath: str) -> List[str]:
    """Loads a list of words from a given file.

    Args:
      filepath: The path to the file containing the words.

    Returns:
      A list of words read from the file.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"Did not find: {filepath}")
    with open(filepath) as f:
        words = f.read().splitlines()
    return sorted(list(set(words)))


@typechecked
def scramble_sankey_data(
    *,
    sankey_df: pd.DataFrame,
    random_words: List[str],
    top_level_categories: List[str],
    separator: str,
    text_column_headers: List[Union[str, int]],
    numeric_column_headers: List[Union[str, int]],
) -> Tuple[pd.DataFrame, Dict[str, str]]:
    unique_atomic_categories = set()

    for text_column_header in text_column_headers:
        unique_atomic_categories.update(
            get_unique_atomic_categories(
                some_df_list=list(sankey_df[text_column_header])
            )
        )
    top_level_categories_copy = top_level_categories.copy() + [separator]
    for skipped_entry in top_level_categories_copy:
        if skipped_entry in unique_atomic_categories:
            unique_atomic_categories.remove(skipped_entry)

    scrambler_map: Dict[str, str] = map_original_to_randomized(
        random_words=random_words,
        original_list=sorted(list(unique_atomic_categories)),
    )
    if len(set(scrambler_map.keys())) != len(scrambler_map.keys()):
        raise ValueError("Found dupes in randomization.")
    if len(set(scrambler_map.values())) != len(scrambler_map.values()):
        raise ValueError("Found dupes in randomization values.")

    # Randomize the dataframe column by column.
    for text_column_header in text_column_headers:
        sankey_df[text_column_header] = scramble_df_column(
            scrambler_map=scrambler_map, some_col=sankey_df[text_column_header]
        )
    for numeric_column_header in numeric_column_headers:
        sankey_df[numeric_column_header] = randomize_list_order_magnitude(
            numbers=list(sankey_df[numeric_column_header]),
            lower=0.12,
            upper=10.2,
        )

    return sankey_df, scrambler_map


@typechecked
def scramble_df_column(
    *, scrambler_map: Dict[str, str], some_col: Series
) -> Series:
    # Create a copy to avoid modifying the original Series directly
    result = some_col.copy()
    for i, entry in enumerate(result):
        atomic_categories: List[str] = entry.split(":")
        for j, atomic_category in enumerate(atomic_categories):
            if atomic_category in scrambler_map:
                atomic_categories[j] = scrambler_map[atomic_category]
        # Update the current row, not the next one
        result.iloc[i] = ":".join(atomic_categories)
    return result


@typechecked
def get_unique_atomic_categories(*, some_df_list: List[str]) -> set[str]:

    unique_atomic_categories: set[str] = set()
    for entry in some_df_list:
        atomic_categories: List[str] = entry.split(":")
        atomic_categories
        for atomic_category in atomic_categories:
            unique_atomic_categories.add(atomic_category)
    return unique_atomic_categories


@typechecked
def map_original_to_randomized(
    *, random_words: List[str], original_list: List[str]
) -> Dict[str, str]:
    """Creates a dictionary mapping elements of original_list to randomly
    selected words from random_words.

    Args:
    random_words: A list of words to be used for mapping.
    original_list: A list of elements to be mapped.

    Returns:
    A dictionary where keys are elements from original_list and values are
    randomly selected words from random_words.
    """
    shuffle_dict: Dict[str, str] = {}
    if len(random_words) < len(original_list):
        raise ValueError(
            f"Please provide more random words than:{len(original_list)}"
        )

    for category in original_list:

        shuffle_dict[category] = get_unique_random_word(
            random_words, shuffle_dict
        )

    if len(shuffle_dict.keys()) != len(original_list):
        raise ValueError(
            "Did not create a mapping for each element in the original list."
        )
    return shuffle_dict


@typechecked
def get_unique_random_word(
    random_words: List[str], shuffle_dict: Dict[str, str]
) -> str:
    """Selects a random word from the given list that is not already present as
    a value in the given dictionary.

    Args:
      random_words: A list of words.
      shuffle_dict: A dictionary.

    Returns:
      The randomly selected word.

    Raises:
      ValueError: If all words in the list have already been used as values in
      the dictionary.
    """

    attempts = 0
    max_attempts = len(random_words)  # Limit attempts to the number of words

    while True:
        if attempts >= max_attempts:
            raise ValueError("All words have already been used.")

        random_index = int(random.uniform(0, len(random_words)))  # nosec
        random_word = random_words[random_index]

        if random_word not in shuffle_dict.values():
            return random_word

        attempts += 1


@typechecked
def randomize_list_order_magnitude(
    numbers: List[float], lower: float, upper: float
) -> List[float]:
    """Randomizes a list of numbers while preserving the order and maintaining
    roughly the same magnitude.

    Args:
        numbers: The input list of numbers.

    Returns:
        A new list with the numbers randomized while preserving order
        and roughly maintaining majgnitude.
    """

    # mean = sum(numbers) / len(numbers)
    multipliers = sorted(
        [random.uniform(lower, upper) for _ in range(len(numbers))]  # nosec
    )

    output_nrs: List[float] = [
        round(num * multiplier, 2)
        for num, multiplier in zip(numbers, multipliers)
    ]
    return output_nrs

"""Handles file reading and writing."""

from typeguard import typechecked


@typechecked
def load_file_to_string(*, filepath: str) -> str:
    """Load the content of a file into a string.

    Args:
        filepath (str): Path to the file to be read.

    Returns:
        str: Content of the file as a string.
    """
    with open(filepath, encoding="utf-8") as file:
        return file.read()

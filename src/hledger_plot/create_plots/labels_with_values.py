# from plotly.graph_objs._figure import Figure


import base64

# Assuming 'fig' is a Plotly Figure object (or similar wrapper)
import numpy as np
from hledger_core.Currency import Currency
from plotly.graph_objects import (
    Figure,  # Import Figure if you have access to it; Import for type hinting if available
)
from plotly.graph_objs import Figure


def format_treemap_labels(fig: Figure, disp_currency: Currency) -> Figure:
    """Add the numeric value to every treemap label and make the parents array
    refer to the *new* labels.

    All labels are guaranteed to be unique (as stated in the question).
    """
    treemap = fig.data[0]  # the only trace

    # ------------------------------------------------------------------ #
    # 1. Labels
    # ------------------------------------------------------------------ #
    old_labels = treemap.labels  # np.ndarray of strings
    n = len(old_labels)

    # ------------------------------------------------------------------ #
    # 2. Values – decode the compressed bdata
    # ------------------------------------------------------------------ #
    val_dict = treemap.values
    if isinstance(val_dict, dict) and "bdata" in val_dict:
        bin_data = base64.b64decode(val_dict["bdata"])
        values = np.frombuffer(bin_data, dtype=val_dict["dtype"])
    else:
        values = np.asarray(val_dict)  # fallback (plain array)

    if len(values) != n:
        raise ValueError(
            f"Labels ({n}) and values ({len(values)}) must have the same"
            " length."
        )

    # ------------------------------------------------------------------ #
    # 3. Build the *new* labels
    # ------------------------------------------------------------------ #
    new_labels_list = []
    for lab, val in zip(old_labels, values):
        # integer values → no decimal part
        val_str = str(int(val)) if val == int(val) else f"{val:.2f}"
        new_labels_list.append(f"{lab} {val_str} {disp_currency}")

    new_labels = np.array(new_labels_list, dtype=object)

    # ------------------------------------------------------------------ #
    # 4. Build a fast old → new mapping (labels are unique)
    # ------------------------------------------------------------------ #
    old_to_new = dict(zip(old_labels, new_labels))

    # ------------------------------------------------------------------ #
    # 5. Rewrite the parents array
    # ------------------------------------------------------------------ #
    old_parents = treemap.parents
    new_parents = np.array(
        [old_to_new.get(p, "") for p in old_parents],  # "" for the root
        dtype=object,
    )

    # ------------------------------------------------------------------ #
    # 6. Write everything back into the trace
    # ------------------------------------------------------------------ #
    treemap.labels = new_labels
    treemap.parents = new_parents
    # `treemap.values` stays the *numeric* array – Plotly needs it for sizing.
    # If you really want the dict form again, you can re-encode it, but it is
    # unnecessary because Plotly will accept a plain np.array as well.

    return fig

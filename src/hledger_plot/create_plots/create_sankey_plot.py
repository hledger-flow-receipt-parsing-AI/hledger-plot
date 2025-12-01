from argparse import Namespace
from typing import Dict, List, Tuple

import pandas as pd
import plotly.graph_objects as go
from pandas.core.frame import DataFrame

# import plotly
from plotly.graph_objs._figure import Figure
from typeguard import typechecked

from hledger_plot.create_plots.scrambler import scramble_sankey_data
from hledger_plot.HledgerCategories import get_parent
from hledger_plot.PlotConfig import PlotConfig


class ColumnNode:
    def __init__(self, index: int, name: str, value: float):
        self.index = index
        self.name = name
        self.value = value


class Position:
    def __init__(self, index: int, name: str, x: float, y: float):
        self.index = index
        self.name = name
        self.x = x
        self.y = y


@typechecked
def store_down_transactions(
    *,
    args: Namespace,
    balance: float,
    full_transaction_category: str,
    parent_account: str,
) -> Tuple[str, str]:
    if balance >= 0:
        if args.verbose:
            print(
                f"DOWN: {balance} -"
                f" S=parent_account={parent_account},T=f"
                f"ull_transaction_category={full_transaction_category}"
            )

        source, target = parent_account, full_transaction_category
    else:
        if args.verbose:
            print(
                f"DOWN: {balance} -"
                " S=full_transaction_category="
                f"{full_transaction_category},T=parent_account="
                f"{parent_account}"
            )
        source, target = full_transaction_category, parent_account
    return source, target


@typechecked
def store_up_transactions(
    *,
    args: Namespace,
    balance: float,
    full_transaction_category: str,
    parent_account: str,
) -> Tuple[str, str]:
    if balance < 0:
        source, target = full_transaction_category, parent_account
        if args.verbose:
            print(
                f"UP: {balance} -"
                " S=full_transaction_category="
                f"{full_transaction_category},T=parent_account={parent_account}"
            )
    else:
        source, target = parent_account, full_transaction_category
        if args.verbose:
            print(
                f"UP: {balance} -"
                f" S=parent_account={parent_account},T="
                f"full_transaction_category={full_transaction_category}"
            )
    return source, target


@typechecked
def get_parent_account(
    *,
    df: DataFrame,
    top_level_account_categories: List[str],
    full_transaction_category: str,
    separator: str,
) -> str:
    # A set of all accounts mentioned in the report, to check that parent
    # accounts have known balance.
    accounts = set(df[0].values)

    # Top-level accounts need to be connected to the special bucket that
    # divides input from output. The name for this bucket is randomly
    # chosen to be: separator.

    if full_transaction_category in top_level_account_categories:
        parent_account = separator
    else:
        parent_account = get_parent(
            transaction_category=full_transaction_category
        )
        if parent_account not in accounts:
            raise Exception(
                f"for account {full_transaction_category}, parent account"
                f" {parent_account} not found - have you forgotten --no-elide?"
            )
    return parent_account


@typechecked
def to_sankey_df(
    *,
    args: Namespace,
    df: DataFrame,
    # top_level_account_categories: List[str],
    desired_left_top_level_categories: List[str],
    desired_right_top_level_categories: List[str],
    plot_config: PlotConfig,
) -> pd.DataFrame:

    # TODO: assert full_transaction category does not contain duplicate values
    # like: assets:windows:assets:moon

    # Create a DataFrame to store the sankey data
    sankey_df: pd.DataFrame = pd.DataFrame(
        columns=["source", "target", "value"]
    )

    # Convert report to the sankey dataframe
    for _, row in df.iterrows():
        full_transaction_category: str = row[0]
        balance: float = row[1]
        parent_account: str = get_parent_account(
            df=df,
            top_level_account_categories=plot_config.top_level_account_categories,
            full_transaction_category=full_transaction_category,
            separator=plot_config.separator,
        )

        # If no desired categories are found, do not add anything to the
        # sankey_df.
        if any(
            top_level_category in full_transaction_category
            for top_level_category in desired_left_top_level_categories
            + desired_right_top_level_categories
        ):
            if any(
                top_level_category in full_transaction_category
                for top_level_category in desired_left_top_level_categories
            ):
                source, target = store_up_transactions(
                    args=args,
                    balance=balance,
                    full_transaction_category=full_transaction_category,
                    parent_account=parent_account,
                )
            elif any(
                top_level_category in full_transaction_category
                for top_level_category in desired_right_top_level_categories
            ):
                source, target = store_down_transactions(
                    args=args,
                    balance=balance,
                    full_transaction_category=full_transaction_category,
                    parent_account=parent_account,
                )
            else:
                # Skip unwanted categories.
                pass
            sankey_df.loc[len(sankey_df)] = {
                "source": source,
                "target": target,
                "value": abs(balance),
            }
    sankey_df.to_csv("sankey.csv", index=False)

    if args.randomize:
        scrambled_df, _ = scramble_sankey_data(
            sankey_df=sankey_df,
            random_words=plot_config.random_words,
            top_level_categories=plot_config.top_level_account_categories,
            separator=plot_config.separator,
            text_column_headers=["source", "target"],
            numeric_column_headers=["value"],
        )
        return scrambled_df
    return sankey_df


@typechecked
def create_column_nodes(
    *,
    nodes: List[str],
    node_columns: Dict[str, int],
    node_values: Dict[int, float],
    max_column: int,
) -> Dict[int, List[ColumnNode]]:
    """Creates a dictionary mapping column indices to lists of nodes.

    Args:
        nodes: A list of node names.
        node_columns: A dictionary mapping node names to their corresponding
        column indices.
        node_values: A list of node values.
        max_column: The maximum column index.

    Returns:
        A dictionary where keys are column indices and values are lists of
        dictionaries,
        each representing a node with its index, name, and value.
    """
    column_nodes: Dict[int, List[ColumnNode]] = {
        i: [] for i in range(max_column + 1)
    }
    for i, node in enumerate(nodes):
        coumn_node: ColumnNode = ColumnNode(
            index=i, name=node, value=node_values[i]
        )
        new_index: int = node_columns[node]
        column_nodes[new_index].append(coumn_node)
    return column_nodes


@typechecked
def calculate_positions(
    column_nodes: Dict[int, List[ColumnNode]],
    max_column: int,
) -> List[Position]:
    """Calculates the x and y positions for each node based on its column and
    value.

    Args:
        column_nodes: A dictionary mapping column indices to lists of nodes.
        max_column: The maximum column index.

    Returns:
        A list of dictionaries, each containing the index, name, x-coordinate,
        and y-coordinate of a node.
    """
    positions: List[Position] = []
    for column, nodes_in_column in column_nodes.items():
        total_value: float = 0
        for columnNode in nodes_in_column:
            total_value += columnNode.value
        # total_value: int = sum(node["value"] for node in nodes_in_column)
        if total_value == 0:  # Handle nodes with no value.

            positions.append(
                Position(
                    index=nodes_in_column[0].index,
                    name=nodes_in_column[0].name,
                    x=0,
                    y=0.5,
                )
            )
            continue
        y_offset: int = 0
        for node in nodes_in_column:
            y_position = y_offset + (node.value / (2 * total_value))
            positions.append(
                Position(
                    index=node.index,
                    name=node.name,
                    x=column / max_column,
                    y=y_position,
                )
            )
            y_offset += int(float(node.value) / total_value)
    return positions


@typechecked
def compute_node_positions(
    *,
    nodes: List[str],
    sources: List[int],
    targets: List[int],
    values: List[float],
) -> List[Position]:
    if not nodes:
        return []  # No nodes → no positions

    if len(sources) != len(targets) or len(sources) != len(values):
        raise ValueError(
            "sources, targets, and values must have the same length"
        )

    if not sources:  # No edges
        # Assign all nodes to column 0
        node_columns: Dict[str, int] = {node: 0 for node in nodes}
    else:
        node_columns: Dict[str, int] = {}
        for i, (source, target) in enumerate(zip(sources, targets)):
            if source < 0 or source >= len(nodes):
                raise IndexError(
                    f"Source index {source} out of bounds for nodes list of"
                    f" length {len(nodes)}"
                )
            if target < 0 or target >= len(nodes):
                raise IndexError(
                    f"Target index {target} out of bounds for nodes list of"
                    f" length {len(nodes)}"
                )

            src_node = nodes[source]
            tgt_node = nodes[target]

            # Initialize source column if not seen
            node_columns[src_node] = node_columns.get(src_node, 0)
            # Target is at least source + 1
            node_columns[tgt_node] = max(
                node_columns.get(tgt_node, 0), node_columns[src_node] + 1
            )

    # Now safe to compute max_column
    max_column = max(node_columns.values()) if node_columns else 0

    node_values: Dict[int, float] = {i: 0 for i in range(len(nodes))}
    for i, (source, target) in enumerate(zip(sources, targets)):
        node_values[target] += values[i]

    column_nodes: Dict[int, List[ColumnNode]] = create_column_nodes(
        nodes=nodes,
        node_columns=node_columns,
        node_values=node_values,
        max_column=max_column,
    )

    return calculate_positions(
        column_nodes=column_nodes,
        max_column=max_column,
    )


@typechecked
def pysankey_plot_with_manual_pos(
    sankey_df: pd.DataFrame, title: str
) -> Figure:

    # Define nodes and links.
    # Sort DataFrame by either 'source' or 'target' column, to make sure that
    # relate accounts stay close together in the initial layout.
    sankey_df.sort_values(by=["target", "source"], inplace=True)

    # Get unique sources and targets for node names
    nodes = pd.concat([sankey_df["source"], sankey_df["target"]]).unique()
    sources: List[int] = []
    targets: List[int] = []
    values: List[float] = []
    for i, x in enumerate(sankey_df["source"]):
        sources.append(list(nodes).index(x))
    for i, x in enumerate(sankey_df["target"]):
        targets.append(list(nodes).index(x))
    for i, x in enumerate(sankey_df["value"]):
        values.append(x)

    node_positions = compute_node_positions(
        nodes=nodes.tolist(), sources=sources, targets=targets, values=values
    )

    # Extract x and y coordinates
    # [pos["x"] for pos in node_positions]
    y_coords = [pos.y for pos in node_positions]

    # Create Sankey diagram
    fig: Figure = go.Figure(
        data=[
            go.Sankey(
                node=dict(
                    pad=15,
                    thickness=20,
                    line=dict(color="black", width=0.5),
                    label=nodes,
                    # x=x_coords,
                    y=y_coords,
                ),
                link=dict(
                    source=sources,
                    target=targets,
                    value=values,
                ),
            ),
        ],
        layout={"title": title, "meta": "sankey"},
    )
    return fig

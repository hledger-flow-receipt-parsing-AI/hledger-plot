"""Make sure the dashboard's port is free before hledger_plot does any work.

Exporting the plots for every period takes minutes; finding out only
afterwards that an earlier dashboard still holds the port wastes them.
"""

import os
import socket
import sys
from typing import List, Optional, Tuple

from typeguard import typechecked

try:  # Optional: only used to say which process holds the port.
    import psutil
except ImportError:  # pragma: no cover - depends on the environment
    psutil = None


@typechecked
def dash_host_and_port() -> Tuple[str, int]:
    """The address the dashboard serves on (Dash's HOST/PORT defaults)."""
    return (
        os.environ.get("HOST", "127.0.0.1"),
        int(os.environ.get("PORT", "8050")),
    )


@typechecked
def port_is_free(*, host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        # Same option as Dash's server, so only a listening socket (not a
        # recently closed connection) counts as busy.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


@typechecked
def _listening_processes(*, port: int) -> List[Tuple[int, str]]:
    """(pid, command line) of each process listening on the port, if known."""
    if psutil is None:
        return []
    try:
        connections = psutil.net_connections(kind="tcp")
    except (psutil.Error, OSError):
        return []
    pids = sorted(
        {
            conn.pid
            for conn in connections
            if conn.pid
            and conn.laddr
            and conn.laddr.port == port
            and conn.status == psutil.CONN_LISTEN
        }
    )
    processes: List[Tuple[int, str]] = []
    for pid in pids:
        try:
            command = " ".join(psutil.Process(pid).cmdline())
        except psutil.Error:
            command = "(unknown command)"
        processes.append((pid, command))
    return processes


@typechecked
def _print_port_in_use(*, port: int) -> None:
    print(f"\nPort {port} is already in use, so the dashboard cannot start.")
    processes = _listening_processes(port=port)
    if processes:
        print("It is held by:")
        for pid, command in processes:
            print(f"  PID {pid}: {command}")
        pids = " ".join(str(pid) for pid, _ in processes)
        print("Stop it with:")
        print(f"  kill {pids}")
    else:
        print("Stop whatever holds it with:")
        print(f"  kill $(lsof -t -iTCP:{port} -sTCP:LISTEN)")
    print(f"Or use another port, e.g.: PORT={port + 1} hledger_plot ...")


@typechecked
def ensure_port_is_free(
    *, host: str, port: int, interactive: Optional[bool] = None
) -> None:
    """Return once the port is free.

    In a terminal, wait for the user to stop the other program and check
    again; otherwise print the kill command and exit.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    while not port_is_free(host=host, port=port):
        _print_port_in_use(port=port)
        if not interactive:
            sys.exit(1)
        try:
            input("Press Enter once it has stopped (Ctrl+C to quit). ")
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)

"""hledger_plot checks the Dash port before it spends minutes on plots.

It used to export every period's plots first and only then fail with
"Address already in use" when an earlier dashboard was still running.
"""

import os
import socket
from argparse import Namespace
from typing import Iterator, List

import pytest

import hledger_plot.__main__ as plot_main
from hledger_plot.plotting_dash import port_check


@pytest.fixture
def busy_socket() -> Iterator[socket.socket]:
    """A socket listening on a free port, like a running dashboard."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    yield sock
    sock.close()


def test_port_is_free_detects_a_listening_socket(
    busy_socket: socket.socket,
) -> None:
    port = busy_socket.getsockname()[1]
    assert not port_check.port_is_free(host="127.0.0.1", port=port)
    busy_socket.close()
    assert port_check.port_is_free(host="127.0.0.1", port=port)


def test_busy_port_prints_kill_command_and_stops_when_not_interactive(
    busy_socket: socket.socket, capsys: pytest.CaptureFixture
) -> None:
    port = busy_socket.getsockname()[1]

    with pytest.raises(SystemExit) as exit_info:
        port_check.ensure_port_is_free(
            host="127.0.0.1", port=port, interactive=False
        )

    assert exit_info.value.code == 1
    out = capsys.readouterr().out
    assert f"Port {port}" in out
    if port_check.psutil is not None:
        assert f"kill {os.getpid()}" in out
    else:
        assert f"lsof -t -iTCP:{port} -sTCP:LISTEN" in out


def test_interactive_run_waits_until_the_port_is_freed(
    busy_socket: socket.socket,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    port = busy_socket.getsockname()[1]
    prompts: List[str] = []

    def user_stops_the_old_dashboard(prompt: str = "") -> str:
        prompts.append(prompt)
        busy_socket.close()
        return ""

    monkeypatch.setattr("builtins.input", user_stops_the_old_dashboard)

    port_check.ensure_port_is_free(
        host="127.0.0.1", port=port, interactive=True
    )

    assert len(prompts) == 1
    assert f"Port {port}" in capsys.readouterr().out


def test_main_checks_the_port_before_exporting_plots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: List[str] = []
    args = Namespace(journal_filepath="/some/all-years.journal")
    monkeypatch.delenv("SKIP_DASH", raising=False)
    monkeypatch.setattr(plot_main, "verify_args", lambda **_: args)
    monkeypatch.setattr(
        plot_main.PlotConfig, "__init__", lambda self, args: None
    )
    monkeypatch.setattr(
        plot_main,
        "ensure_port_is_free",
        lambda **_: steps.append("port check"),
    )
    monkeypatch.setattr(
        plot_main,
        "export_plots_for_all_times",
        lambda **_: steps.append("export"),
    )
    monkeypatch.setattr(
        plot_main,
        "launch_dash_dashboard",
        lambda **_: steps.append("dashboard"),
    )

    plot_main.main()

    assert steps == ["port check", "export", "dashboard"]


def test_main_skips_the_port_check_without_a_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: List[str] = []
    args = Namespace(journal_filepath="/some/all-years.journal")
    monkeypatch.setenv("SKIP_DASH", "true")
    monkeypatch.setattr(plot_main, "verify_args", lambda **_: args)
    monkeypatch.setattr(
        plot_main.PlotConfig, "__init__", lambda self, args: None
    )
    monkeypatch.setattr(
        plot_main,
        "ensure_port_is_free",
        lambda **_: steps.append("port check"),
    )
    monkeypatch.setattr(
        plot_main,
        "export_plots_for_all_times",
        lambda **_: steps.append("export"),
    )

    plot_main.main()

    assert steps == ["export"]

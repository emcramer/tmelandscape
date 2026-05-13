"""Phase 0 smoke tests: package imports, version, CLI + MCP entry points wire up."""

from __future__ import annotations

from importlib.metadata import version as _installed_version

from typer.testing import CliRunner

import tmelandscape
from tmelandscape.cli.main import app
from tmelandscape.mcp.server import mcp, ping


def test_version_agrees_with_installed_metadata() -> None:
    assert isinstance(tmelandscape.__version__, str)
    assert tmelandscape.__version__ == _installed_version("tmelandscape")


def test_cli_version_command() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert tmelandscape.__version__ in result.stdout


def test_mcp_server_registered_ping() -> None:
    # Sanity: the FastMCP instance exists and has a name.
    assert mcp.name == "tmelandscape"


def test_mcp_ping_returns_version() -> None:
    payload = ping()
    assert payload["status"] == "ok"
    assert payload["version"] == tmelandscape.__version__

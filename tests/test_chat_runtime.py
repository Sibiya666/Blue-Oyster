"""Exercise the actual probe and plugin registration without installing Hermes/Discord."""
import json
from pathlib import Path
import runpy
import sys
from types import ModuleType

import pytest


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[1]
    (tmp_path / "plugins").mkdir()
    (tmp_path / "plugins/barman").symlink_to(repo / "barman", target_is_directory=True)
    config = {"plugins": {"enabled": ["barman"]}, "platform_toolsets": {"discord": []}}
    (tmp_path / "config.yaml").write_text(json.dumps(config))
    (tmp_path / ".env").write_text("BARMAN_SCOPE_CHANNEL=50\n")
    package = ModuleType("hermes_cli")
    plugins = ModuleType("hermes_cli.plugins")
    plugins.VALID_HOOKS = {"pre_gateway_dispatch", "transform_llm_output"}
    yaml = ModuleType("hermes_yaml")
    yaml.safe_load = json.loads
    monkeypatch.setitem(sys.modules, "hermes_cli", package)
    monkeypatch.setitem(sys.modules, "hermes_cli.plugins", plugins)
    monkeypatch.setitem(sys.modules, "hermes_yaml", yaml)
    check = runpy.run_path(str(repo / "deploy/check_chat_runtime.py"))["check"]
    return tmp_path, config, check


def test_probe_registers_real_plugin_with_hermes_yaml(runtime):
    home, _, check = runtime
    check(home)


def test_probe_rejects_missing_scope(runtime):
    home, _, check = runtime
    (home / ".env").write_text("")
    with pytest.raises(AssertionError, match="scope channel"):
        check(home)


def test_probe_rejects_nonempty_toolset(runtime):
    home, config, check = runtime
    config["platform_toolsets"]["discord"] = ["terminal"]
    (home / "config.yaml").write_text(json.dumps(config))
    with pytest.raises(AssertionError, match="empty"):
        check(home)

"""Read-only deploy probe before widening channels. Run inside the target container."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def check(home: Path):
    from hermes_cli.plugins import VALID_HOOKS
    required = {"pre_gateway_dispatch", "transform_llm_output"}
    assert required <= VALID_HOOKS, "Hermes lacks barman chat policy hooks"
    import yaml
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert "barman" in config.get("plugins", {}).get("enabled", []), "barman plugin is not enabled"
    assert config.get("platform_toolsets", {}).get("discord") == [], "Discord toolset must be empty"
    spec = importlib.util.spec_from_file_location("barman_probe", home / "plugins/barman/__init__.py",
                                                submodule_search_locations=[str(home / "plugins/barman")])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    hooks = {}
    ctx = SimpleNamespace(_manager=SimpleNamespace(home_path=home),
                          register_platform_handler=lambda *args: None,
                          register_hook=lambda name, callback, **kw: hooks.update({name: callback}))
    module.register(ctx)
    assert required <= hooks.keys(), "barman failed to register chat policy"


if __name__ == "__main__":
    check(Path(sys.argv[1]))

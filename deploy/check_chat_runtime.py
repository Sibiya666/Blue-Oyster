"""Read-only deploy probe before widening channels. Run inside the target container."""
import importlib.util
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace


def check(home: Path):
    from hermes_cli.plugins import PluginContext, VALID_HOOKS
    required = {"pre_gateway_dispatch", "transform_llm_output"}
    assert required <= VALID_HOOKS, "Hermes lacks barman chat policy hooks"
    import hermes_yaml as yaml  # Hermes ships ruamel.yaml, not necessarily PyYAML.
    config = yaml.safe_load((home / "config.yaml").read_text())
    assert "barman" in config.get("plugins", {}).get("enabled", []), "barman plugin is not enabled"
    assert config.get("platform_toolsets", {}).get("discord") == [], "Discord toolset must be empty"
    assert config.get("streaming", {}).get("enabled") is False, "streaming must be disabled before shortening"
    spec = importlib.util.spec_from_file_location("barman_probe", home / "plugins/barman/__init__.py",
                                                submodule_search_locations=[str(home / "plugins/barman")])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    env = module._env(home)
    scope = env.get("BARMAN_SCOPE_CHANNEL") or env.get("BARMAN_ROLES_CHANNEL", "")
    assert scope.isdecimal() and int(scope) > 0, "configure a server scope channel before widening access"
    hooks = {}
    def register_hook(name, callback, **kwargs):
        # Check the REAL installed API, not only our test facade's permissive signature.
        inspect.signature(PluginContext.register_hook).bind(None, name, callback, **kwargs)
        hooks[name] = callback

    ctx = SimpleNamespace(_manager=SimpleNamespace(home_path=home),
                          register_platform_handler=lambda *args: None,
                          register_hook=register_hook)
    module.register(ctx)
    assert required <= hooks.keys(), "barman failed to register chat policy"


if __name__ == "__main__":
    check(Path(sys.argv[1]))

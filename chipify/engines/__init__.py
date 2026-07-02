# Copyright (c) 2026 Santiago Hofwimmer
"""
engines – Modular simulator-engine registry for Chipify.

Mirrors the GUI plugin system (:mod:`chipify.plugin_loader`): each supported
circuit simulator is one :class:`~chipify.engines.base.BaseSimulator`
subclass, registered under its ``name``. The sweep orchestrator
(:mod:`chipify.simulator`), the datasheet schema, the CLI and the GUI all
resolve engines through this registry, so adding a simulator is a single
class in a single file — no other module needs editing.

Adding an engine
----------------
1. **Built-in** — add ``chipify/engines/<name>.py`` with the engine class and
   one entry in :data:`_BUILTIN_IMPORTS` below. Imports stay lazy: the module
   is only loaded when the engine is first used, keeping datasheet validation
   and GUI startup light.

2. **Drop-in plugin** — put a file in ``~/.chipify/plugins/`` (or the
   ``CHIPIFY_PLUGINS`` directory) defining a ``BaseSimulator`` subclass with a
   unique ``name``. It is discovered lazily, exactly like PlotPlugin /
   QtTabPlugin files (see PLUGINS.md, "Simulator engine plugin"). Keep such
   files import-light: worker processes import them when a datasheet selects
   the engine.

3. **Programmatic** — ``register_engine(MyEngine)`` (usable as a decorator),
   e.g. from test code or an embedding application.

Engine *names* travel to worker processes (pickled on each Test); classes are
re-resolved inside the worker via :func:`get_engine`, so all three
registration paths work with the multiprocessing pool.
"""
from __future__ import annotations

import importlib
import logging

from chipify.engines.base import BaseSimulator

log = logging.getLogger("chipify.engines")

DEFAULT_ENGINE = "ngspice"


class UnknownEngineError(KeyError):
    """Raised when an engine name is not registered (and no plugin provides it)."""


#: Built-in engines, resolved lazily by import path so that importing this
#: package (e.g. for datasheet validation) does not load simulator modules.
_BUILTIN_IMPORTS: dict[str, tuple[str, str]] = {
    "ngspice": ("chipify.engines.ngspice", "NgspiceSimulator"),
    "vacask":  ("chipify.engines.vacask", "VacaskSimulator"),
}

_registered: dict[str, type[BaseSimulator]] = {}
_plugin_engines: "dict[str, type[BaseSimulator]] | None" = None


def register_engine(cls: type[BaseSimulator]) -> type[BaseSimulator]:
    """Register a BaseSimulator subclass under its ``name`` (decorator-friendly).

    The name must be non-empty and not ``"base"``; re-registering a name
    replaces the previous class with a warning (mirrors plugin_loader's
    duplicate handling).
    """
    name = str(getattr(cls, "name", "")).strip().lower()
    if not name or name == "base":
        raise ValueError(
            f"Engine class {cls.__name__} must define a unique non-empty 'name'."
        )
    if name in _registered and _registered[name] is not cls:
        log.warning("Engine %r re-registered: %r replaces %r.",
                    name, cls, _registered[name])
    _registered[name] = cls
    return cls


def _discover_plugin_engines() -> dict[str, type[BaseSimulator]]:
    """Scan the plugin directory for BaseSimulator subclasses (cached).

    Built-in / programmatically registered names win over plugin files of the
    same name (consistent with how the datasheet schema validates them).
    """
    global _plugin_engines
    if _plugin_engines is None:
        from chipify.plugin_loader import discover_plugin_classes
        found: dict[str, type[BaseSimulator]] = {}
        try:
            classes = discover_plugin_classes(BaseSimulator)
        except Exception:
            log.warning("Engine plugin discovery failed.", exc_info=True)
            classes = []
        for cls in classes:
            name = str(getattr(cls, "name", "")).strip().lower()
            if not name or name == "base":
                log.warning("Engine plugin %s has no usable 'name' – skipped.",
                            getattr(cls, "__name__", cls))
                continue
            if name in _BUILTIN_IMPORTS or name in _registered or name in found:
                log.warning("Engine plugin %r shadows an existing engine – skipped.",
                            name)
                continue
            found[name] = cls  # type: ignore[assignment]
        _plugin_engines = found
    return _plugin_engines


def engine_names(include_plugins: bool = True) -> tuple[str, ...]:
    """All selectable engine names: built-ins, registered, then plugins."""
    names = list(_BUILTIN_IMPORTS)
    names += [n for n in _registered if n not in names]
    if include_plugins:
        names += [n for n in _discover_plugin_engines() if n not in names]
    return tuple(names)


def get_engine_class(name: str) -> type[BaseSimulator]:
    """Resolve an engine name to its class, raising UnknownEngineError."""
    key = str(name or DEFAULT_ENGINE).strip().lower()
    if key in _registered:
        return _registered[key]
    if key in _BUILTIN_IMPORTS:
        mod_name, cls_name = _BUILTIN_IMPORTS[key]
        cls = getattr(importlib.import_module(mod_name), cls_name)
        _registered[key] = cls
        return cls
    plugins = _discover_plugin_engines()
    if key in plugins:
        return plugins[key]
    raise UnknownEngineError(
        f"Unknown simulator engine {name!r}; available: {', '.join(engine_names())}"
    )


def get_engine(name: str) -> BaseSimulator:
    """Instantiate the engine registered under *name* (raises UnknownEngineError)."""
    return get_engine_class(name)()


def netlist_extension(name: str) -> str:
    """Netlist-template file extension for engine *name* (``.spice`` fallback
    for unknown names, so display/export paths never hard-fail)."""
    try:
        return get_engine_class(name).netlist_ext
    except UnknownEngineError:
        return BaseSimulator.netlist_ext


def resolve_engine_name(test, override: "str | None" = None,
                        cfg: "dict | None" = None) -> str:
    """Resolve the concrete engine name for *test* — most specific wins.

    Precedence: the testbench's own ``engine`` → the run *override* (CLI
    ``--simulator``) → the ``simulator_engine`` setting → ``ngspice``.
    """
    cfg = cfg if cfg is not None else {}
    name = (getattr(test, "engine", None) or override
            or cfg.get("simulator_engine") or DEFAULT_ENGINE)
    return str(name).strip().lower()


def engine_selector():
    """Return a ``test -> BaseSimulator`` selector caching one instance per name.

    Used wherever several testbenches share engines (template generation in
    the main process, case batches inside each worker) so a mixed-engine
    datasheet instantiates every engine exactly once per process.
    """
    cache: dict[str, BaseSimulator] = {}

    def _engine_for(test) -> BaseSimulator:
        name = resolve_engine_name(test)
        if name not in cache:
            cache[name] = get_engine(name)
        return cache[name]

    return _engine_for


def reload_engines() -> None:
    """Clear the plugin-engine cache; plugins re-scan on next access."""
    global _plugin_engines
    _plugin_engines = None

"""
loaders/core/registry.py — Plugin discovery and ranking.

Plugins live in loaders/plugins/<name>.py and subclass SourcePlugin. The
registry imports them all on demand and provides:

  - get_all() → all registered plugins
  - get_by_name(name) → plugin by short name (e.g. "KGS")
  - detect_best(path) → list of (plugin, ConfidenceScore) sorted by score
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from loaders.core.plugin_base import SourcePlugin, ConfidenceScore


def get_all() -> list[SourcePlugin]:
    """
    Discover all SourcePlugin subclasses in loaders.plugins.
    Each discovered class is instantiated once.
    """
    import loaders.plugins  # the package

    discovered: list[SourcePlugin] = []
    for _, modname, _ in pkgutil.iter_modules(loaders.plugins.__path__):
        full_name = f"loaders.plugins.{modname}"
        try:
            module = importlib.import_module(full_name)
        except Exception as e:
            print(f"WARN: could not import plugin module {full_name}: {e}")
            continue

        for name, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, SourcePlugin)
                and cls is not SourcePlugin
                and cls.__module__ == full_name  # only classes defined here
            ):
                try:
                    discovered.append(cls())
                except Exception as e:
                    print(f"WARN: could not instantiate {name}: {e}")

    return discovered


def get_by_name(name: str) -> SourcePlugin | None:
    """Return the plugin whose .name matches (case-insensitive)."""
    name_lower = name.lower()
    for p in get_all():
        if p.name.lower() == name_lower:
            return p
    return None


def detect_best(path: Path) -> list[tuple[SourcePlugin, ConfidenceScore]]:
    """
    Run detect() on every plugin against `path` and return results
    sorted descending by score. Plugins returning score 0 are included
    in the list (so the UI can show "all plugins gave 0, please choose").
    """
    results: list[tuple[SourcePlugin, ConfidenceScore]] = []
    for plugin in get_all():
        try:
            score = plugin.detect(path)
        except Exception as e:
            score = ConfidenceScore(0, f"detect() raised: {e}")
        results.append((plugin, score))

    results.sort(key=lambda x: -x[1].score)
    return results

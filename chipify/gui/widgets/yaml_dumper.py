"""
yaml_dumper.py – Custom YAML representers for the datasheet editor.

Registers two representers on the global yaml.Dumper / yaml.SafeDumper:

* Lists are serialised in flow-style (inline) so that ``[1, 2, 3]`` is
  written on a single line rather than as a block sequence.
* ``QuotedString`` instances are written with single-quote scalar style so
  that string values like ``'typical'`` survive a YAML round-trip.

Import this module once at application startup (gui/main_window.py) and the
representers become active for all subsequent ``yaml.dump()`` calls.
"""
from __future__ import annotations

from typing import Any

import yaml


class QuotedString(str):
    """Marker subclass: YAML-dumps with single-quote style."""


def represent_list_inline(dumper: yaml.Dumper, data: list[Any]) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def represent_quoted_str(dumper: yaml.Dumper, data: QuotedString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")


def register() -> None:
    """Register the custom representers on all three YAML dumper classes."""
    for dumper_cls in (yaml.Dumper, yaml.SafeDumper):
        dumper_cls.add_representer(list, represent_list_inline)  # type: ignore[arg-type]
        dumper_cls.add_representer(QuotedString, represent_quoted_str)  # type: ignore[arg-type]
    yaml.add_representer(list, represent_list_inline)
    yaml.add_representer(QuotedString, represent_quoted_str)

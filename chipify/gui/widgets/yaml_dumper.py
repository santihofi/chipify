"""
yaml_dumper.py – Custom YAML dumper for the datasheet editor.

``ChipifyDumper`` extends ``yaml.Dumper`` with two representers:

* Lists are serialised in flow-style (inline) so that ``[1, 2, 3]`` is
  written on a single line rather than as a block sequence.
* ``QuotedString`` instances are written with single-quote scalar style so
  that string values like ``'typical'`` survive a YAML round-trip.

The representers are registered on this dumper class only — registering on
the global ``yaml.Dumper``/``SafeDumper`` would silently change the output of
every other ``yaml.dump()`` call in the process (project_config.save, plugins,
third-party code). Pass ``Dumper=ChipifyDumper`` at the call site:

    yaml.dump(data, Dumper=yaml_dumper.ChipifyDumper, ...)
"""
from __future__ import annotations

from typing import Any

import yaml


class QuotedString(str):
    """Marker subclass: YAML-dumps with single-quote style."""


class ChipifyDumper(yaml.Dumper):
    """yaml.Dumper with chipify's datasheet-editor formatting conventions."""


def represent_list_inline(dumper: yaml.Dumper, data: list[Any]) -> yaml.SequenceNode:
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)


def represent_quoted_str(dumper: yaml.Dumper, data: QuotedString) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="'")


def register() -> None:
    """Register the custom representers on ChipifyDumper (idempotent)."""
    ChipifyDumper.add_representer(list, represent_list_inline)
    ChipifyDumper.add_representer(QuotedString, represent_quoted_str)

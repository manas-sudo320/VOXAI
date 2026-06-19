"""Shared type aliases used by core infrastructure."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import TypeAlias

ConfigScalar: TypeAlias = str | int | float | bool
ConfigValue: TypeAlias = ConfigScalar | list["ConfigValue"] | dict[str, "ConfigValue"]
ConfigMapping: TypeAlias = Mapping[str, ConfigValue]
MutableConfigMapping: TypeAlias = MutableMapping[str, ConfigValue]

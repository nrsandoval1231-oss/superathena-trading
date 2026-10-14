"""Load strategy manifests and import their real entrypoints."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from athena_trading.paths import repo_root

ALWAYS_REQUIRED = ("id", "version", "status")
RUNTIME_REQUIRED = ("promotion", "overnight", "authority")
_ABSENT_ENTRYPOINT = frozenset({"", "null", "none"})


@dataclass(frozen=True)
class StrategyManifest:
    path: Path
    fields: dict[str, str]

    @property
    def id(self) -> str:
        return self.fields["id"]


def specification_only(fields: dict[str, str]) -> bool:
    """A research archive is registered and is not an importable runtime."""
    if fields.get("status") == "research-specification-only":
        return True
    return fields.get("execution_enabled", "").lower() == "false"


def parse_manifest(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw[:1].isspace() or raw.lstrip().startswith("-"):
            continue
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"manifest line {lineno} is not key: value")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key:
            raise ValueError(f"manifest line {lineno} is empty")
        if not value:
            continue
        if key in fields:
            raise ValueError(f"duplicate manifest key {key}")
        fields[key] = value
    missing = [key for key in ALWAYS_REQUIRED if key not in fields]
    if missing:
        raise ValueError(f"manifest missing {missing}")
    if specification_only(fields):
        return fields
    entry = fields.get("entrypoint", "").lower()
    missing.extend(key for key in RUNTIME_REQUIRED if key not in fields)
    if entry in _ABSENT_ENTRYPOINT:
        missing.append("entrypoint")
    if missing:
        raise ValueError(f"manifest missing {missing}")
    return fields


def discover(root: Path | None = None) -> list[StrategyManifest]:
    base = root or repo_root()
    found: list[StrategyManifest] = []
    for path in sorted((base / "strategies").rglob("strategy.yaml")):
        if "_template" in path.parts:
            continue
        found.append(StrategyManifest(path, parse_manifest(path.read_text(encoding="utf-8"))))
    return found


def load_entrypoint(manifest: StrategyManifest):
    """Import the manifest entrypoint. This does not submit an order."""
    entry = manifest.fields.get("entrypoint", "").strip()
    if entry.lower() in _ABSENT_ENTRYPOINT:
        raise ValueError(f"{manifest.id} has no importable entrypoint")
    return importlib.import_module(entry)

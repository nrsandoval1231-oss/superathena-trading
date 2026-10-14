"""Load strategy manifests and import their real entrypoints."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path

from athena_trading.paths import repo_root

REQUIRED = (
    "id",
    "version",
    "status",
    "entrypoint",
    "promotion",
    "overnight",
    "authority",
)


@dataclass(frozen=True)
class StrategyManifest:
    path: Path
    fields: dict[str, str]

    @property
    def id(self) -> str:
        return self.fields["id"]


def parse_manifest(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            raise ValueError(f"manifest line {lineno} is not key: value")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or not value:
            raise ValueError(f"manifest line {lineno} is empty")
        if key in fields:
            raise ValueError(f"duplicate manifest key {key}")
        fields[key] = value
    missing = [key for key in REQUIRED if key not in fields]
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
    return importlib.import_module(manifest.fields["entrypoint"])

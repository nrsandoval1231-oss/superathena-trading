"""Checkout-root lookup that does not depend on package depth."""
from __future__ import annotations

from pathlib import Path


def find_repo_root() -> Path | None:
    """Return the checkout that holds ``configs``, if this process is inside one."""
    start = Path(__file__).resolve()
    for parent in start.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "configs").is_dir():
            return parent
    return None


def repo_root() -> Path:
    """Return the SuperAthena checkout. Fail closed outside that checkout."""
    root = find_repo_root()
    if root is None:
        raise RuntimeError(
            "SuperAthena checkout was not found from "
            f"{Path(__file__).resolve()}. Research identity paths resolve only "
            "inside the repository."
        )
    return root


def config_file(*parts: str) -> Path:
    """Resolve a tracked config without preventing an installed import.

    Inside the checkout this is ``<root>/configs/<parts>``. An installed copy
    has no config tree; the returned path does not exist, so a later read
    fails closed instead of opening some other file.
    """
    root = find_repo_root()
    if root is None:
        return Path("/nonexistent/superathena/configs").joinpath(*parts)
    return root.joinpath("configs", *parts)

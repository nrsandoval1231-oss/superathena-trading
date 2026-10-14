"""Strategy discovery uses the migrated implementations."""
from __future__ import annotations

import ast
from pathlib import Path

from athena_trading.execution.authority import AuthorityError, ExecutionAuthority, parse_authority
from athena_trading.position_management.apde import APDEState, ORDER
from athena_trading.strategy_registry import discover, load_entrypoint, specification_only

ROOT = Path(__file__).resolve().parents[1]
PRODUCT_ROOTS = (
    "strategies/momentum/orb-m",
    "strategies/custom/predictive-intraday",
    "strategies/event-driven/earnings-adaptive",
    "operations/paper-trading",
    "core",
    "data/ingestion/market_data",
    "evaluation",
)
BANNED = ("aat_v1", "aat_v2")


def _imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _banned(name: str) -> bool:
    parts = name.split(".")
    return any(part in BANNED for part in parts)


def test_strategy_manifests_register_real_entrypoints():
    manifests = discover(ROOT)
    assert [item.id for item in manifests] == [
        "athena-retention-geometry",
        "legacy-strategy-research",
        "predictive-intraday",
        "earnings-adaptive",
        "orb-momentum",
    ]
    archive = manifests[0]
    assert specification_only(archive.fields)
    assert archive.fields["status"] == "research-specification-only"
    assert archive.fields["entrypoint"] == "null"
    assert archive.fields["execution_enabled"] == "false"
    assert archive.fields["archive_only"] == "true"
    try:
        load_entrypoint(archive)
    except ValueError as exc:
        assert archive.id in str(exc)
    else:
        raise AssertionError("archive entrypoint was imported")
    for manifest in manifests:
        if specification_only(manifest.fields):
            continue
        assert manifest.fields["promotion"] == "not-promoted"
        assert manifest.fields["overnight"] == "forbidden"
        assert manifest.fields["authority"] == "PAPER-or-ABSENT"
        assert manifest.fields["status"] != "live"
        load_entrypoint(manifest)
        secondary = manifest.fields.get("secondary_entrypoint")
        if secondary:
            assert secondary == "athena_trading.aat_v2"
            __import__(secondary)


def test_product_code_does_not_import_legacy_experiments():
    offenders = []
    for relative in PRODUCT_ROOTS:
        for path in (ROOT / relative).rglob("*.py"):
            if any(_banned(name) for name in _imported(path)):
                offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_exogenous_package_stays_independent_of_orb_and_legacy_code():
    banned = {"orb_m", "aat_v1"}
    offenders = []
    root = ROOT / "data/ingestion/exogenous"
    for path in root.rglob("*.py"):
        for name in _imported(path):
            if any(part in banned for part in name.split(".")):
                offenders.append(f"{path.relative_to(ROOT)}:{name}")
    assert offenders == []


def test_live_authority_remains_rejected_and_apde_order_is_unchanged():
    assert [state.value for state in ORDER] == [
        "EXPLORE", "PROTECT", "HARVEST", "DEFEND", "EXIT",
    ]
    assert list(ExecutionAuthority) == [ExecutionAuthority.ABSENT, ExecutionAuthority.PAPER]
    try:
        parse_authority("LIVE")
    except AuthorityError as exc:
        assert "LIVE" in str(exc)
    else:
        raise AssertionError("LIVE was accepted")
    halt = (ROOT / "core/risk/risk/halt.py").read_text(encoding="utf-8")
    apde = (ROOT / "core/portfolio/position_management/apde.py").read_text(encoding="utf-8")
    assert "jev" not in halt.lower()
    assert "astra" not in apde.lower()
    assert APDEState.EXIT.value == "EXIT"

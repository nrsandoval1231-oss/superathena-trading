"""Write the local hash-bound AAT-V1 TRAINING protocol amendment."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from athena_trading.aat_v1.amendment import build_protocol_amendment


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--transport-ledger", type=Path, required=True)
    parser.add_argument("--scoring-config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("refusing to overwrite protocol amendment")
    amendment = build_protocol_amendment(
        args.protocol, args.transport_ledger, args.scoring_config
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(amendment, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

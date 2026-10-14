# Fixture self-improve lab

> The role labels below belong to this offline toy. Its “Astra gate” is deterministic code, not the owner-selected **Astra 6** LLM; it does not implement the [Astra 6 + Jev target](HYBRID_MODEL_CONTRACT.md). No toy receipt promotes policy into the active runner.

Offline toy inside Athena Trading. It mutates management knobs on synthetic bars and writes receipts. Execution authority stays **ABSENT**. Nothing is sent to a broker. A PASS on these bars is not a promotion and not evidence of trading performance.

Aura is a separate harness. This repository does not import it, and this lab does not put trading into Aura. Astra Desk stays in its own repository. The AAT-V1 holdout is not read.

## Role map

| Aura-style role | This lab | What it is allowed to do |
|---|---|---|
| Sol | `MutationScope` from `default_scope()` | Name scalar `ManagementParameters` fields and a step. Constitution fields, mappings, and sizing fields are rejected. |
| DeepSeek, or a local mutator | `propose_candidates()` | Change one scoped field through `ManagementParameters.evolve()`. No model API and no network call. An illegal step is FAIL and is not replaced with a different field. |
| Astra gate | `judge_search()` and `judge_holdout()` | Return PASS, FAIL, or UNKNOWN from the precommitted `GatePolicy`. The mutator does not edit that policy. |
| Market lab | Athena Trading paper walker | `walk_paper_session()` on the fixture bars with `ExecutionAuthority.ABSENT`. Simulated episode R comes from `run_symbol_session()`, the engine the walker already uses. `FixtureBroker` submissions stay at zero. |

Repos stay separate. The paper pilot, learning store, and live runner are not updated by a receipt.

## Loop

1. The builtin catalog is split before any mutation. Search sessions are chronological. The later holdout is hashed. Search receives that hash, not the bars.
2. Walk-forward inside search: the earliest `max(1, n // 3)` sessions are a burn-in fold. The later sessions are the only sample the survive gate reads.
3. Each candidate is one adaptive-surface step, up and down, except a boolean field which is a single flip.
4. The best PASS candidate becomes the next search parent when one exists. The next generation mutates that parent and scores the same sealed search partition again. `promoted_to_paper_pilot` stays false.
5. After every generation receipt is on disk, the holdout opens once. Survivors from every generation are scored against the original parent. Those labels are not fed back into search.

The default command runs three generations. On the builtin spike fold, search keeps raising `peak_retention` because that fold pays a tighter trail. The holdout then fails that chain. A different generation-0 survivor can pass the holdout and still lose the search seed, because the holdout is not an input.

## Gates

Search, selection fold only:

| Verdict | Rule |
|---|---|
| UNKNOWN | Fewer than 2 closed simulated episodes |
| PASS | Mean simulated R is at least 0.05R above the parent |
| FAIL | Otherwise, including ties, regressions, and illegal mutations |

Holdout, after search, against the generation-0 parent:

| Verdict | Rule |
|---|---|
| UNKNOWN | Fewer than 1 closed episode, or the move is inside ±0.05R |
| PASS | Mean simulated R beats the parent by at least 0.05R |
| FAIL | Mean simulated R is at least 0.05R worse |

UNKNOWN does not survive. A holdout PASS is still not written into the paper pilot.

## Run

```bash
python -m pip install pytest ruff==0.15.8 .
python scripts/run_fixture_self_improve.py --out /tmp/fixture-self-improve
```

`--generations` defaults to 3. `--out` is required. `-h` prints help. The process writes `generation-000.json` through `generation-002.json`, `holdout-evaluation.json`, `summary.json`, and `report.md`. Stdout is the same markdown report. It refuses `LIVE`, refuses an `--authority` flag, and refuses to overwrite generation receipts. Later generations reuse the same search bars and still do not open the holdout until the end.

## What this is not

Synthetic bars, zero slippage on the fixture constitution, and a five-field scope. Costs and risk ceilings stay constitutional. The lab does not call Alpaca or TypeSafe, does not enable LIVE, and does not consume the AAT-V1 holdout. It does not register a learning rule. See [LEARNING.md](LEARNING.md) for the separate paper-pilot study.

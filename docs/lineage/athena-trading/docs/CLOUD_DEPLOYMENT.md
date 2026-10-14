# Continuous cloud paper operation

> **Current-runner runbook; hybrid target is not deployed by this document.** The active intraday runner remains Jev-only. The 13 October owner direction selects Astra 6 + Jev; follow the [hybrid contract](HYBRID_MODEL_CONTRACT.md) and [build plan](BUILD_PLAN.md) before changing that runtime. Astra 6's provider deployment and API model ID are unverified. This document performs no installation, paid calls, or broker operations.

Deploy the existing active paper runner on one persistent Linux VPS. The active host is a Hostinger VPS, installed on 10 October 2026. A DigitalOcean Droplet remains an optional path. Either host uses the same `deploy/install.sh`, `athena-paper.service`, and root-owned `/etc/athena/paper.env`. The service stays online across market sessions and reboots; entries remain restricted to the broker's market session and the bounded policy in [LIVE_PAPER.md](LIVE_PAPER.md). The bounded learning review is implemented. A separate Jev-only earnings paper service is defined in [EARNINGS_PAPER.md](EARNINGS_PAPER.md). It is not enabled by the intraday installer until an operator preflights it, and it is not deployed by this branch. The hybrid Earnings arm, full APDE, and general Core integration remain incomplete. Nick confirmed no overnight positions on 13 October 2026; the earnings book now pursues same-session exits and cannot grant multi-day holding permission.

## Existing Jev-only setup

| Component | Choice |
|---|---|
| Active host | Hostinger VPS, installed 10 October 2026. `athena-paper.service` is enabled. Plan size, address, and SSH account are not recorded here |
| Optional host | DigitalOcean Basic, Regular CPU, 1 vCPU, 2 GiB RAM, 50 GiB disk; $12/month base cap; Ubuntu 24.04 LTS in an available US East region. Not the host of the 10 October install |
| Decision model | TypeSafe `jev-1.13.0`; the only model in the active path |
| Learning | Immediate reconciled experience; nightly prospective validation after 20:15 Eastern |
| Broker | Dedicated Alpaca paper account; IEX unless SIP is explicitly subscribed/configured |
| Runtime | One systemd service, one session child; no local model or GPU |
| Persistent state | `/var/lib/athena/YYYY-MM-DD.sqlite`, retained across restarts and days |
| Secrets | Root-owned `/etc/athena/paper.env`, mode 0600; injected by systemd |
| Access | SSH key; inbound SSH restricted to the operator; no public application port required |

The $12 is the server charge, not an all-in trading budget. API usage, optional backups, taxes, and any paid market-data entitlement are separate. Each session permits at most 20 candidate reviews, each with at most one Jev call. Jev state is capped at 24 KB; failed inference is not retried automatically. Nightly learning uses deterministic code and makes no paid model calls. These are usage bounds, not a guaranteed dollar ceiling. Set provider spending controls for the intended account budget.

A Hostinger VPS with a persistent disk fits the existing SQLite runtime. A DigitalOcean Droplet is the same kind of host. DigitalOcean App Platform has ephemeral local filesystems and does not support persistent volumes; using it would require moving state to another service. Begin with one host and measure memory/disk growth before increasing resources. The Droplet row is an initial sizing choice for that optional path, not a load-test result, a Hostinger invoice, or an uptime guarantee.

## Future hybrid deployment gate

Resolve and pin the owner-selected **Astra 6** provider deployment/API model ID, access and interface before creating an integration. No Astra 6 endpoint, SDK or credential name is prescribed here because none has been verified. No silent model substitution is allowed. The environment files and service/installer do not configure Astra 6. The shared-risk repair only adds the dedicated entry coordination path described below.

Extend this runtime with bounded event-driven Astra 6 proposals and Jev judgments, separate call/cost/latency budgets, evidence and plan expiry, identity/version health and operator alerts. Neither model may stall broker protection, mandatory exits or restart recovery. Add shared portfolio accounting before treating two books' individual limits as a portfolio guarantee. Keep one reconciled source of account exposure; do not launch parallel services from a future architecture description.

PR #29's Jev-only earnings book is on this branch and is still unmerged. The owner resolved its holding policy on 13 October 2026: no overnight positions. New earnings brackets are DAY orders; exits start 15 minutes before the actual regular-session close, including early closes. Legacy journals remain recoverable. `EXIT_UNRESOLVED` requires operator attention when the market is closed; broker outages or halts can prevent actual flatness, and pending fills remain `FLATTENING`. This policy decision is not deployment authorization. Hybrid configuration, preflight, rollout, rollback, alerts and restore tests remain implementation deliverables. This runbook does not install either service.

## Install a reviewed revision

Use the existing Hostinger VPS, or optionally create the configured Droplet in the owner's account. Authorize any displayed recurring charge before creating a new host. Do not place credentials in cloud-init, the repository, command arguments, or chat. Use the owner's existing SSH access. Enable host monitoring and configure backups under the chosen budget. This runbook does not record a host address, an SSH user name, or the contents of `paper.env`.

Clone `nrsandoval1231-oss/athena-trading` into `/opt/athena-trading` using the owner's authorized repository access. Pass `install.sh` the full SHA of the checkout you intend to run. The 10 October 2026 paper-readiness audit named `d36164ef7843d135dbfeea3684be598566abcf33`, when that audit's paper runner still matched `733a1c441dbed15799397192cf6470b46c370d45`. Session-resilience changes landed later that day, so a later reviewed SHA is a valid install argument when it is that checkout's `HEAD`. The installer refuses a SHA that is not the checkout's `HEAD`. This runbook does not record the SHA installed on the Hostinger VPS. As root on that host:

```bash
athena_revision=FULL_REVIEWED_40_CHARACTER_COMMIT_SHA
git -C /opt/athena-trading checkout --detach "$athena_revision"
bash /opt/athena-trading/deploy/install.sh "$athena_revision"
sudoedit /etc/athena/paper.env
```

The installer rejects a dirty or mismatched checkout and an already active service. It installs the package and service definition, creates a restricted runtime user and state directory, and leaves the service stopped. Populate the three credential values (Alpaca key/secret and TypeSafe key) and the explicitly chosen `ATHENA_SYMBOL` in the environment file. No symbol or secret is supplied by the installer. Optional `ATHENA_JEV_MIN_PTAKE`, `ATHENA_JEV_MIN_CONFIDENCE`, and `ATHENA_FALLBACK_AFTER_OPEN_MINUTES` override the paper gate and the daily fallback cutoff. Leave them unset to use the defaults in [LIVE_PAPER.md](LIVE_PAPER.md).

Terra/OpenAI and Ollama are removed from the active code and environment template. Existing reserved entries retain their original complete policy binding for model-free recovery; old model packages and credentials are not required.

## Shared-account entry coordination

Both services on this single Linux host must use the same absolute `ATHENA_SHARED_RISK_DIR=/var/lib/athena-risk` and the actual peer journal paths (`ATHENA_STATE_DIR` and `ATHENA_EARNINGS_STATE_DIR`). The units set these paths. The installer creates the separate shared directory with mode 0700, owned by `athena`; files remain mode 0600 under UMask 0077. `ProtectSystem=strict` stays enabled. Each service retains its existing own write paths and adds only `/var/lib/athena-risk`; neither gains write access to the peer's trading journal directory.

New entry acquires a nonblocking account-specific file lock before fresh broker reads, exposure checks and durable intent. A contender defers entry. The mutex remains held through submission/acknowledgement; a crash releases only the lock, while the durable intent continues reserving capacity. Buying power is sampled after positions and orders, so an order seen later cannot be exempted from an older balance. Pending and unacknowledged intents remain counted. Peer reads verify the hash chain and durable checkpoint without taking the peer's writer lock or writing its files. Prior-session unresolved journals and GTC `done_for_day` reservations are retained.

For direct CLI use, export the same `ATHENA_SHARED_RISK_DIR` explicitly, including when only one arm runs. Missing, relative, inaccessible or inconsistent coordination paths fail closed for new entry. The provider preflight alone does not establish coordination readiness. A durable journal binding records account and resolved coordination directory; changing it requires stopping both services and reconciling the existing state, not deleting the binding or starting a fresh journal. Do not remove a live lock file, run mixed old/new entry code, or split these file-based books across hosts. This is single-host coordination, not a distributed lock service.

Protective management, kill switches and same-session exits never acquire the entry mutex or wait for a model. A failed coordinator blocks new risk, not management of existing exposure. The permission tests use an unprivileged process with read-only peer files; no real systemd service was launched as part of this repair. Stop and reconcile both services before any separately authorized upgrade, retain their journals and checkpoint sidecars, then verify the exact installed revision and operator-visible state. This documentation does not authorize deployment.

## Preflight and activate

Run the no-order preflight under the service identity, with systemd loading the environment file:

```bash
systemd-run --wait --pipe --collect --unit=athena-paper-preflight \
  --property=User=athena \
  --property=WorkingDirectory=/opt/athena-trading \
  --property=EnvironmentFile=/etc/athena/paper.env \
  /bin/sh -c 'exec /opt/athena-trading/.venv/bin/python scripts/run_athena_paper.py --symbol "$ATHENA_SYMBOL" --feed "$ATHENA_FEED" --authority PAPER --journal /var/lib/athena/preflight.sqlite --preflight'
```

Require `ok: true`, Jev and the intended symbol/feed, and a flat dedicated paper account. This verifies authentication/model availability and account reads; it does not perform inference or submit an order. Market-data freshness, asset eligibility and risk are checked in the active session.

`deploy/install.sh` also installs `athena-earnings.service` and, when missing, `/etc/athena/earnings.env` from the example. It leaves that service stopped. Do not enable it in the same step as the intraday service. Preflight and the ownership rules are in [EARNINGS_PAPER.md](EARNINGS_PAPER.md). The two units use different state directories and different env files. They can share one Alpaca paper account. The intraday unit is given `ATHENA_EARNINGS_STATE_DIR` so it does not flatten `athe-` positions.

Then start the authorized active paper service and follow its first market session:

```bash
systemctl enable --now athena-paper.service
systemctl status athena-paper.service --no-pager
journalctl -u athena-paper.service -f
cat /var/lib/athena/health.json
```

Record the installed commit, successful provider preflight, startup status and actual broker results separately from tests. A running process or heartbeat alone does not prove a trade, confirmed flatness, or adjudication quality. A session that receives at least one TAKE_TRADE label can reserve one paper order through the normal gate. After the cutoff, the journaled fallback submits only when the fresh bar is still that setup. A stale bar or a changed direction records a no-trade and does not send the old order. A session with no TAKE_TRADE label can still finish with no order. A model error is not an approval. A malformed Jev answer is journaled and vetoes that setup; it does not by itself delete other TAKE_TRADE labels. On 13 October 2026 one paper bracket filled and was flattened seconds later by a held-stop visibility bug. That event is recorded in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md). It is not a performance result.

## Daily operation and recovery

The supervisor checks broker session state, sleeps between checks, and starts the same paper CLI when the market is open. A fresh session gets a dated journal. A finished or halted day is not restarted for more entries. Old journals are retained and verified; an unresolved entry takes priority over today's session, including outside market hours. Multiple unresolved sessions or a corrupt journal block new entries.

Recovery uses the original journal's symbol, feed and policy binding. A reserved entry can reconcile and close without TypeSafe credentials. It still needs the broker and writable state. The service never restores a backup automatically, creates a fresh journal to bypass a halt, or blindly resends a reserved entry. Broker client IDs remain stable per account/session.

A flat account with no reserved order does not get a `RUNNER_ERROR` halt for a stale bar, a missing opening minute, or a startup/model-list failure. The supervisor retries that journal. `entry_not_created` (`BROKER_ORDER_NOT_FOUND`) finishes the reserved id after two flat HTTP 404s and does not submit it again. A halt with no reserved entry still finishes that dated journal: operator stop, daily loss, or visible exposure. systemd restart does not clear a halt that was written.

The child begins flattening 15 minutes before the broker-reported close, including early closes. A missed close or date rollover ends an empty cloud session. An unresolved position continues recovery rather than authorizing the next day. A per-session halt without exposure permits a fresh journal on the next market day; to suspend all future sessions, stop the service.

```bash
systemctl stop athena-paper.service
```

SIGTERM requests the child's existing halt and cleanup path. The service allows up to 210 seconds for shutdown. If the broker cannot confirm flat, exposure remains unresolved and must be inspected in the paper account. Confirm positions and orders before host upgrades, shutdown, backup restore or replacement. A restored disk may omit recent events: reconcile against the broker before activation, and never run the restored host alongside the original.

`health.json` reports the supervisor state and timestamp; journald contains child transitions and failures. Neither is an external alert. Configure monitoring for service failure, stale heartbeat, unresolved exposure and low disk space before treating the first deployment as unattended. The learning store lives under `/var/lib/athena/learning/`; dated JSON reports summarize decisions, observed trade outcomes and candidate/validation/promotion history. Back up each SQLite file together with its `.checkpoint` sidecar, keeping the service stopped and broker state reconciled. The sidecar detects ordinary tail deletion; it is not an off-host tamper-proof anchor. Completed journals grow over time and currently remain on disk; no retention deletion is automated. Broker outages, a host failure or a trading halt can defeat pre-close liquidation.

## Verified state and references

As of 24 September 2026 the Jev/learning revision had **657 root tests and 158 Astra tests** passing, with repo-wide Ruff 0.15.8 clean. As of 10 October 2026 Astra Desk is a separate repository, current main at the paper-readiness audit was `d36164ef7843d135dbfeea3684be598566abcf33`, and GitHub Actions run `38073284465` on that push succeeded. Flat-day data and startup errors retry; a halt that was written, or `entry_not_created`, finishes that dated journal. See [the paper-readiness audit](audits/2026-10-10-paper-readiness.md) and [LIVE_PAPER.md](LIVE_PAPER.md#recovery-and-exits). Exact tested revision and command evidence are in [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

**Hostinger paper pilot, 10 October 2026.** Nick installed this runner on a Hostinger VPS with `deploy/install.sh`, `athena-paper.service`, and root-owned `/etc/athena/paper.env`. The service is enabled. That environment file holds the Alpaca paper and TypeSafe keys. The values stay on the host and are not in this repository. The service was last observed in `WAITING_FOR_MARKET`, waiting for Monday open. Pre-Monday fixture, preflight, and health checks passed that day. Those checks show the install and connectivity. They are not a broker fill, a traded session, or a performance result. **LIVE remains rejected.** This document does not record which commit SHA that host is running.

DigitalOcean remains an optional host with the same installer, service, and environment file. A Droplet has not been provisioned from this repository. On 24 September 2026 the DigitalOcean console returned “Site Unavailable” in this workspace browser on the initial visit and one reload, and no DigitalOcean credential was in the connected catalog. That note is not the Hostinger install. Earlier no-order/no-session statements described the September snapshot. The dated 13 October [held-bracket incident](IMPLEMENTATION_STATUS.md#held-bracket-stop--13-october-2026) records a filled paper bracket and flatten, superseding it. This review does not establish the current deployed SHA, host health, open exposure or performance improvement.

Primary documentation checked on the status date:

- [DigitalOcean Droplet pricing](https://www.digitalocean.com/pricing/droplets), [creation](https://docs.digitalocean.com/products/droplets/how-to/create/) and [App Platform filesystem limits](https://docs.digitalocean.com/products/app-platform/details/limits/).
- Broker and Jev references are maintained in [LIVE_PAPER.md](LIVE_PAPER.md#verified-api-references).

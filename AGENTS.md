# Working in SuperAthena Trading

Read [the architecture](docs/architecture/README.md) and [implementation status](docs/migration/STATUS.md) before changing strategy behavior.

## Safety

- LIVE is not an authority. Do not add it.
- Do not change approved risk limits, the ORB constitution, overnight policy, or promotion status.
- Both arms stay flat by the regular close. Earnings DAY orders and the pre-close exit stay in place.
- Do not activate APDE threshold proposals or inactive portfolio limits by choosing a number.
- Consumed holdouts and `INVALID_EVIDENCE` artifacts are immutable.
- Earnings confirmation for a new gate requires a verified issuer release or filing. Do not treat the headline heuristic as that gate, and do not invent a filing source.
- Do not import `aat_v1` or `aat_v2` from product code.
- Astra 6 stays unwired until its provider and model id are verified. Do not substitute another model.
- Do not deploy, restart, or retarget `athena-paper.service`. The live process is the source checkout, not this migration.
- Do not copy secrets or private trading journals into git.
- Athena Core stays an external, unmigrated dependency. Nick excluded it from this migration on 2026-10-14. Do not vendor it.

Historical operating notes from Athena Trading are in `docs/lineage/athena-trading/`. They do not override this file.

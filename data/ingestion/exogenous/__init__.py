"""Point-in-time exogenous (non-price) evidence for AAT-V2.

Proposed in ``docs/AAT_V2_VISION.md``; sources specified in
``docs/EXOGENOUS_SOURCES_V1.md``.  This package holds no registered evidence and
supports no claim.  It must never import from ``orb_m`` or ``aat_v1``: the
deterministic strategy stays runnable with this directory deleted.
"""

from .alfred import (
    AlfredError,
    MissingAlfredCredentialsError,
    alfred_adapter,
    annotate_alfred_revisions,
    fetch_alfred_observations,
    stamp_scheduled_availability,
)
from .analysts import (
    COMPRESSOR_VERSION,
    AnalystError,
    compress_all,
    compressor_identity,
    coverage,
    feature_keys,
)
from .buckets import ABSENT, bucket, ratio_bucket
from .gdelt import GdeltError, parse_gkg_row
from .contracts import (
    SOURCES,
    ExogenousContractError,
    ExogenousLeakageError,
    ExogenousRecord,
    assert_no_lookahead,
    parse_record,
    visible_records,
)
from .ingest import (
    IngestError,
    assert_stable_availability,
    load_record_store,
    normalize,
    passthrough_adapter,
    write_record_store,
)
from .snapshot import (
    SnapshotError,
    build_snapshot,
    compress_opportunity,
    coverage_rates,
    load_opportunity_index,
)

__all__ = [
    "ABSENT", "COMPRESSOR_VERSION", "SOURCES", "AlfredError", "AnalystError",
    "ExogenousContractError", "ExogenousLeakageError", "ExogenousRecord", "IngestError",
    "MissingAlfredCredentialsError", "SnapshotError", "alfred_adapter",
    "annotate_alfred_revisions", "assert_no_lookahead", "assert_stable_availability",
    "bucket", "build_snapshot", "compress_all", "compress_opportunity",
    "compressor_identity", "coverage", "coverage_rates", "feature_keys",
    "fetch_alfred_observations", "GdeltError", "load_opportunity_index", "load_record_store",
    "normalize", "parse_gkg_row", "parse_record", "passthrough_adapter", "ratio_bucket",
    "stamp_scheduled_availability", "visible_records", "write_record_store",
]

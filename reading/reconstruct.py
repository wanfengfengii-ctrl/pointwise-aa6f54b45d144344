from dataclasses import dataclass
import sqlite3

from ingest.records import RevisionKey
from packing.addresses import PackAddress
from packing.chains import IncompleteEvidence, materialize_value
from reading.resolve import resolve_entry


class EvidenceMismatch(IncompleteEvidence):
    pass


@dataclass(frozen=True, slots=True)
class RestoredEntry:
    revision: RevisionKey
    value: bytes


def reconstruct_entry(
    db: sqlite3.Connection, address: PackAddress, expected_revision: RevisionKey | None = None,
) -> RestoredEntry:
    restored = materialize_value(address, lambda position: resolve_entry(db, position))
    if expected_revision is not None and restored.revision != expected_revision:
        raise EvidenceMismatch(f'revision at {address!r} does not match the manifest')
    return RestoredEntry(restored.revision, restored.value)

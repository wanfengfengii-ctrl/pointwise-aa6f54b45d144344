from collections.abc import Iterable
from dataclasses import dataclass

from ingest.records import RevisionKey
from packing.addresses import PackAddress
from reading.reconstruct import RestoredEntry
from snapshot.manifest import SnapshotManifest


@dataclass(frozen=True, slots=True)
class AuditRow:
    position: int
    address: PackAddress
    revision: RevisionKey
    value: bytes

    @property
    def byte_length(self) -> int:
        return len(self.value)


@dataclass(frozen=True, slots=True)
class AuditResult:
    snapshot_id: str
    rows: tuple[AuditRow, ...]

    @property
    def total_bytes(self) -> int:
        return sum(row.byte_length for row in self.rows)


def assemble_audit(manifest: SnapshotManifest, values: Iterable[RestoredEntry]) -> AuditResult:
    rows = tuple(
        AuditRow(position, pinned.address, restored.revision, restored.value)
        for position, (pinned, restored) in enumerate(zip(manifest.entries, values, strict=True))
    )
    return AuditResult(manifest.snapshot_id, rows)

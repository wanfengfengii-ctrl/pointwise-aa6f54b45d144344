from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import sqlite3

from ingest.records import InvalidObservation, validate_identifier
from maintenance.transactions import write_transaction
from packing.addresses import InvalidPackAddress, PackAddress, validate_pack_address
from packing.chains import IncompleteEvidence
from reading.reconstruct import reconstruct_entry
from snapshot.catalog import get_manifest_bytes, save_manifest
from snapshot.manifest import (
    ManifestEntry, ManifestError, SnapshotManifest, parse_manifest, serialize_manifest,
)
from snapshot.receipts import PublicationReceipt, load_publication_receipt, save_publication_receipt


class PublicationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class PublicationResult:
    manifest: bytes
    receipt: PublicationReceipt


def _reissue(
    db: sqlite3.Connection, snapshot_id: str, addresses: tuple[PackAddress, ...], payload: bytes,
) -> PublicationResult:
    manifest = parse_manifest(payload)
    if manifest.snapshot_id != snapshot_id:
        raise PublicationError('stored manifest belongs to another snapshot')
    if tuple(item.address for item in manifest.entries) != addresses:
        raise PublicationError(f'different selection for snapshot {snapshot_id}')
    receipt = load_publication_receipt(db, snapshot_id)
    digest = hashlib.sha256(payload).hexdigest()
    if receipt is None or receipt.manifest_sha256 != digest or receipt.record_count != len(addresses):
        raise PublicationError(f'incomplete publication evidence for {snapshot_id}')
    return PublicationResult(payload, receipt)


def publish_snapshot(
    db: sqlite3.Connection, snapshot_id: str, addresses: Sequence[PackAddress],
) -> PublicationResult:
    try:
        validate_identifier(snapshot_id, 'snapshot id')
        try:
            ordered = tuple(addresses)
        except TypeError as exc:
            raise PublicationError('expected ordered snapshot addresses') from exc
        for address in ordered:
            validate_pack_address(address)
        with write_transaction(db):
            previous = get_manifest_bytes(db, snapshot_id)
            if previous is not None:
                return _reissue(db, snapshot_id, ordered, previous)
            entries = []
            total_bytes = 0
            for address in ordered:
                restored = reconstruct_entry(db, address)
                entries.append(ManifestEntry(address, restored.revision))
                total_bytes += len(restored.value)
            payload = serialize_manifest(SnapshotManifest(snapshot_id, tuple(entries)))
            receipt = PublicationReceipt(
                snapshot_id, len(entries), total_bytes, hashlib.sha256(payload).hexdigest(),
            )
            save_manifest(db, snapshot_id, payload)
            save_publication_receipt(db, receipt)
            return PublicationResult(payload, receipt)
    except (InvalidObservation, InvalidPackAddress, IncompleteEvidence, ManifestError) as exc:
        raise PublicationError(f'cannot publish {snapshot_id!r}: {exc}') from exc

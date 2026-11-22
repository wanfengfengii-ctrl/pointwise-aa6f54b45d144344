import sqlite3

from ingest.records import InvalidObservation, validate_identifier
from maintenance.transactions import read_transaction
from packing.chains import IncompleteEvidence
from reading.audit import AuditResult, assemble_audit
from reading.reconstruct import reconstruct_entry
from snapshot.catalog import get_manifest_bytes
from snapshot.manifest import ManifestError, SnapshotManifest, parse_manifest


class SnapshotReadError(ValueError):
    pass


def _open_in_view(db: sqlite3.Connection, selector: str | bytes) -> SnapshotManifest:
    if isinstance(selector, bytes):
        manifest = parse_manifest(selector)
        if get_manifest_bytes(db, manifest.snapshot_id) != selector:
            raise SnapshotReadError(f'no exact published manifest for {manifest.snapshot_id}')
        return manifest
    validate_identifier(selector, 'snapshot id')
    payload = get_manifest_bytes(db, selector)
    if payload is None:
        raise SnapshotReadError(f'unknown snapshot {selector}')
    manifest = parse_manifest(payload)
    if manifest.snapshot_id != selector:
        raise SnapshotReadError(f'manifest belongs to another snapshot: {selector}')
    return manifest


def open_snapshot(db: sqlite3.Connection, selector: str | bytes) -> SnapshotManifest:
    try:
        with read_transaction(db):
            return _open_in_view(db, selector)
    except (InvalidObservation, ManifestError) as exc:
        raise SnapshotReadError(str(exc)) from exc


def read_snapshot(db: sqlite3.Connection, selector: str | bytes) -> AuditResult:
    try:
        with read_transaction(db):
            manifest = _open_in_view(db, selector)
            values = (reconstruct_entry(db, item.address, item.revision) for item in manifest.entries)
            return assemble_audit(manifest, values)
    except (InvalidObservation, ManifestError, IncompleteEvidence) as exc:
        raise SnapshotReadError(str(exc)) from exc

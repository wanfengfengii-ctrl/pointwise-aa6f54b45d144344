import sqlite3

from ingest.catalog import find_revision
from ingest.records import InvalidObservation, validate_identifier
from maintenance.transactions import read_transaction
from packing.chains import IncompleteEvidence
from reading.audit import AuditResult, ContributionResult, ContributionRow, assemble_audit
from reading.provenance import ContributionSpan
from reading.reconstruct import reconstruct_entry
from snapshot.catalog import get_manifest_bytes
from snapshot.contributions import StoredPosition, load_contribution_evidence
from snapshot.manifest import ManifestError, SnapshotManifest, parse_manifest


class SnapshotReadError(ValueError):
    pass


class MissingContributionEvidence(SnapshotReadError):
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


def _check_spans(spans: tuple[ContributionSpan, ...], value: bytes) -> None:
    cursor = 0
    for span in spans:
        if span.out_start != cursor or span.source is None:
            raise SnapshotReadError('contribution spans do not tile the value')
        if span.byte_length != span.source_end - span.source_start:
            raise SnapshotReadError('contribution span length does not match its source range')
        cursor = span.out_end
    if cursor != len(value):
        raise SnapshotReadError('contribution spans do not cover the value')


def _check_sources(db: sqlite3.Connection, spans: tuple[ContributionSpan, ...], value: bytes) -> None:
    for span in spans:
        key = span.source
        original = find_revision(db, key)
        if original is None:
            raise SnapshotReadError(f'unknown source revision {key!r}')
        if span.source_end > len(original):
            raise SnapshotReadError(f'source range exceeds revision {key!r}')
        if original[span.source_start:span.source_end] != value[span.out_start:span.out_end]:
            raise SnapshotReadError(f'contribution bytes disagree with revision {key!r}')


def _assemble_contributions(
    db: sqlite3.Connection, manifest: SnapshotManifest, stored: tuple[StoredPosition, ...],
) -> ContributionResult:
    if len(stored) != len(manifest.entries):
        raise SnapshotReadError('contribution evidence position count differs from the manifest')
    rows = []
    for position, (item, evidence) in enumerate(zip(manifest.entries, stored, strict=True)):
        if evidence.address != item.address or evidence.revision != item.revision:
            raise SnapshotReadError(f'contribution evidence disagrees with the manifest at {position}')
        restored = reconstruct_entry(db, item.address, item.revision)
        if len(restored.value) != evidence.byte_length:
            raise SnapshotReadError(f'contribution length disagrees with restored bytes at {position}')
        _check_spans(evidence.spans, restored.value)
        _check_sources(db, evidence.spans, restored.value)
        rows.append(ContributionRow(
            position, item.address, restored.revision, restored.value,
            tuple(span.as_public() for span in evidence.spans),
        ))
    return ContributionResult(manifest.snapshot_id, tuple(rows))


def read_contributions(db: sqlite3.Connection, selector: str | bytes) -> ContributionResult:
    try:
        with read_transaction(db):
            manifest = _open_in_view(db, selector)
            stored = load_contribution_evidence(db, manifest.snapshot_id)
            if stored is None:
                raise MissingContributionEvidence(
                    f'snapshot {manifest.snapshot_id} has no contribution evidence')
            return _assemble_contributions(db, manifest, stored)
    except MissingContributionEvidence:
        raise
    except (InvalidObservation, ManifestError, IncompleteEvidence, ValueError) as exc:
        raise SnapshotReadError(str(exc)) from exc

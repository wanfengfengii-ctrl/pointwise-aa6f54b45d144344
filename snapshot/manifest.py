from dataclasses import dataclass
import json

from ingest.records import InvalidObservation, RevisionKey, validate_identifier, validate_revision_key
from packing.addresses import InvalidPackAddress, PackAddress, validate_pack_address


class ManifestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    address: PackAddress
    revision: RevisionKey


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    snapshot_id: str
    entries: tuple[ManifestEntry, ...]


def serialize_manifest(manifest: SnapshotManifest) -> bytes:
    try:
        validate_identifier(manifest.snapshot_id, 'snapshot id')
        rows = []
        for item in manifest.entries:
            validate_pack_address(item.address)
            validate_revision_key(item.revision)
            rows.append([
                item.address.pack_id, item.address.slot, item.revision.source,
                item.revision.record, item.revision.revision,
            ])
        return json.dumps([1, manifest.snapshot_id, rows], separators=(',', ':')).encode('ascii')
    except (InvalidObservation, InvalidPackAddress) as exc:
        raise ManifestError(str(exc)) from exc


def parse_manifest(payload: bytes) -> SnapshotManifest:
    if not isinstance(payload, bytes):
        raise ManifestError('manifest must be bytes')
    try:
        document = json.loads(payload.decode('ascii'))
    except (ValueError, RecursionError) as exc:
        raise ManifestError('invalid manifest encoding') from exc
    if not isinstance(document, list) or len(document) != 3:
        raise ManifestError('invalid manifest structure')
    version, snapshot_id, rows = document
    if type(version) is not int or version != 1 or not isinstance(rows, list):
        raise ManifestError('unsupported manifest structure')
    entries = []
    for row in rows:
        if not isinstance(row, list) or len(row) != 5:
            raise ManifestError('invalid manifest entry')
        pack_id, slot, source, record, revision = row
        entries.append(ManifestEntry(PackAddress(pack_id, slot), RevisionKey(source, record, revision)))
    manifest = SnapshotManifest(snapshot_id, tuple(entries))
    if serialize_manifest(manifest) != payload:
        raise ManifestError('manifest bytes are not canonical')
    return manifest

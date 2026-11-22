from dataclasses import dataclass
import sqlite3

from packing.addresses import PackAddress
from packing.chains import IncompleteEvidence
from packing.format import DeltaEntry
from reading.reconstruct import EvidenceMismatch
from reading.resolve import resolve_entry
from snapshot.catalog import iter_published_manifests
from snapshot.manifest import ManifestError, parse_manifest


@dataclass(frozen=True, slots=True)
class RetirementDependencies:
    pack_id: str
    addresses: tuple[PackAddress, ...]


def collect_retirement_dependencies(db: sqlite3.Connection, pack_id: str) -> RetirementDependencies:
    completed: set[PackAddress] = set()
    needed: set[PackAddress] = set()
    for snapshot_id, payload in iter_published_manifests(db):
        manifest = parse_manifest(payload)
        if manifest.snapshot_id != snapshot_id:
            raise ManifestError(f'manifest belongs to another snapshot: {snapshot_id}')
        for root in manifest.entries:
            entry = resolve_entry(db, root.address)
            if entry.revision != root.revision:
                raise EvidenceMismatch(f'revision at {root.address!r} does not match the manifest')
            current = root.address
            path: set[PackAddress] = set()
            while current not in completed:
                if current in path:
                    raise IncompleteEvidence(f'cycle at {current!r}')
                path.add(current)
                if current.pack_id == pack_id:
                    needed.add(current)
                if not isinstance(entry, DeltaEntry):
                    break
                current = entry.base
                if current not in completed:
                    entry = resolve_entry(db, current)
            completed.update(path)
    return RetirementDependencies(pack_id, tuple(sorted(needed)))

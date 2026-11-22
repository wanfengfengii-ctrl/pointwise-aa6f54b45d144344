from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3

from ingest.records import RevisionKey
from packing.addresses import PackAddress
from reading.provenance import ContributionSpan


@dataclass(frozen=True, slots=True)
class StoredPosition:
    address: PackAddress
    revision: RevisionKey
    byte_length: int
    spans: tuple[ContributionSpan, ...]


def create_contribution_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS contribution_snapshots (
            snapshot_id TEXT NOT NULL PRIMARY KEY REFERENCES snapshots(snapshot_id)
        ) WITHOUT ROWID
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS contribution_positions (
            snapshot_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 0),
            pack_id TEXT NOT NULL,
            slot INTEGER NOT NULL CHECK (slot >= 0),
            source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            byte_length INTEGER NOT NULL CHECK (byte_length >= 0),
            PRIMARY KEY (snapshot_id, position),
            FOREIGN KEY (snapshot_id) REFERENCES contribution_snapshots(snapshot_id)
        ) WITHOUT ROWID
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS contribution_spans (
            snapshot_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 0),
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            out_start INTEGER NOT NULL CHECK (out_start >= 0),
            out_end INTEGER NOT NULL CHECK (out_end >= out_start),
            source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            source_start INTEGER NOT NULL CHECK (source_start >= 0),
            source_end INTEGER NOT NULL CHECK (source_end >= source_start),
            PRIMARY KEY (snapshot_id, position, ordinal),
            FOREIGN KEY (snapshot_id) REFERENCES contribution_snapshots(snapshot_id)
        ) WITHOUT ROWID
    ''')


def is_contribution_snapshot(db: sqlite3.Connection, snapshot_id: str) -> bool:
    return db.execute(
        'SELECT 1 FROM contribution_snapshots WHERE snapshot_id=?', (snapshot_id,),
    ).fetchone() is not None


def save_contribution_snapshot(
    db: sqlite3.Connection, snapshot_id: str, positions: Sequence[StoredPosition],
) -> None:
    db.execute('INSERT INTO contribution_snapshots(snapshot_id) VALUES (?)', (snapshot_id,))
    for index, item in enumerate(positions):
        db.execute('''
            INSERT INTO contribution_positions(
                snapshot_id, position, pack_id, slot, source, record_id, revision_id, byte_length
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            snapshot_id, index, item.address.pack_id, item.address.slot,
            item.revision.source, item.revision.record, item.revision.revision,
            item.byte_length,
        ))
        for ordinal, span in enumerate(item.spans):
            if span.source is None:
                raise ValueError('published contribution spans must have a source revision')
            db.execute('''
                INSERT INTO contribution_spans(
                    snapshot_id, position, ordinal, out_start, out_end,
                    source, record_id, revision_id, source_start, source_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                snapshot_id, index, ordinal, span.out_start, span.out_end,
                span.source.source, span.source.record, span.source.revision,
                span.source_start, span.source_end,
            ))


def load_contribution_evidence(
    db: sqlite3.Connection, snapshot_id: str,
) -> tuple[StoredPosition, ...] | None:
    if not is_contribution_snapshot(db, snapshot_id):
        return None
    spans: dict[int, list[ContributionSpan]] = {}
    for position, out_start, out_end, source, record, revision, start, end in db.execute('''
        SELECT position, out_start, out_end, source, record_id, revision_id,
               source_start, source_end
        FROM contribution_spans WHERE snapshot_id=? ORDER BY position, ordinal
    ''', (snapshot_id,)):
        spans.setdefault(position, []).append(ContributionSpan(
            out_start, out_end, RevisionKey(source, record, revision), start, end,
        ))
    positions = []
    for position, pack_id, slot, source, record, revision, byte_length in db.execute('''
        SELECT position, pack_id, slot, source, record_id, revision_id, byte_length
        FROM contribution_positions WHERE snapshot_id=? ORDER BY position
    ''', (snapshot_id,)):
        if position != len(positions):
            raise ValueError(f'contribution positions are not contiguous at {position}')
        positions.append(StoredPosition(
            PackAddress(pack_id, slot), RevisionKey(source, record, revision), byte_length,
            tuple(spans.get(position, ())),
        ))
    extra = sorted(set(spans) - set(range(len(positions))))
    if extra:
        raise ValueError(f'contribution spans without a position: {extra}')
    return tuple(positions)

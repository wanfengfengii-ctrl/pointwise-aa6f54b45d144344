from collections.abc import Iterator
import sqlite3


def create_snapshot_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS snapshots (
            snapshot_id TEXT NOT NULL PRIMARY KEY,
            manifest BLOB NOT NULL
        ) WITHOUT ROWID
    ''')


def save_manifest(db: sqlite3.Connection, snapshot_id: str, manifest: bytes) -> None:
    db.execute('INSERT INTO snapshots(snapshot_id, manifest) VALUES (?, ?)', (snapshot_id, manifest))


def get_manifest_bytes(db: sqlite3.Connection, snapshot_id: str) -> bytes | None:
    row = db.execute('SELECT manifest FROM snapshots WHERE snapshot_id=?', (snapshot_id,)).fetchone()
    return None if row is None else row[0]


def iter_published_manifests(db: sqlite3.Connection) -> Iterator[tuple[str, bytes]]:
    yield from db.execute('SELECT snapshot_id, manifest FROM snapshots ORDER BY snapshot_id')

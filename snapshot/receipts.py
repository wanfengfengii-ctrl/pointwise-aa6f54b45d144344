from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    snapshot_id: str
    record_count: int
    total_bytes: int
    manifest_sha256: str


def create_publication_receipt_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS publication_receipts (
            snapshot_id TEXT NOT NULL PRIMARY KEY REFERENCES snapshots(snapshot_id),
            record_count INTEGER NOT NULL CHECK (record_count >= 0),
            total_bytes INTEGER NOT NULL CHECK (total_bytes >= 0),
            manifest_sha256 TEXT NOT NULL
        ) WITHOUT ROWID
    ''')


def save_publication_receipt(db: sqlite3.Connection, receipt: PublicationReceipt) -> None:
    db.execute('''
        INSERT INTO publication_receipts(snapshot_id, record_count, total_bytes, manifest_sha256)
        VALUES (?, ?, ?, ?)
    ''', (receipt.snapshot_id, receipt.record_count, receipt.total_bytes, receipt.manifest_sha256))


def load_publication_receipt(db: sqlite3.Connection, snapshot_id: str) -> PublicationReceipt | None:
    row = db.execute('''
        SELECT snapshot_id, record_count, total_bytes, manifest_sha256
        FROM publication_receipts WHERE snapshot_id=?
    ''', (snapshot_id,)).fetchone()
    return None if row is None else PublicationReceipt(*row)

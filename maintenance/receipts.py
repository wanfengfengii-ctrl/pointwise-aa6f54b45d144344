from dataclasses import dataclass
import sqlite3


@dataclass(frozen=True, slots=True)
class RetirementReceipt:
    pack_id: str
    removed_bytes: int
    preserved_addresses: int


def create_retirement_receipt_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS retirement_receipts (
            pack_id TEXT NOT NULL PRIMARY KEY REFERENCES pack_activity(pack_id),
            removed_bytes INTEGER NOT NULL CHECK (removed_bytes >= 0),
            preserved_addresses INTEGER NOT NULL CHECK (preserved_addresses >= 0)
        ) WITHOUT ROWID
    ''')


def save_retirement_receipt(db: sqlite3.Connection, receipt: RetirementReceipt) -> None:
    db.execute('''
        INSERT INTO retirement_receipts(pack_id, removed_bytes, preserved_addresses)
        VALUES (?, ?, ?)
    ''', (receipt.pack_id, receipt.removed_bytes, receipt.preserved_addresses))


def load_retirement_receipt(db: sqlite3.Connection, pack_id: str) -> RetirementReceipt | None:
    row = db.execute('''
        SELECT pack_id, removed_bytes, preserved_addresses FROM retirement_receipts WHERE pack_id=?
    ''', (pack_id,)).fetchone()
    return None if row is None else RetirementReceipt(*row)

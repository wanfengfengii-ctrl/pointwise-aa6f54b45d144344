import sqlite3

from packing.addresses import PackAddress, validate_pack_address
from packing.format import PackEntry, decode_pack


class PackStoreError(ValueError):
    pass


def create_pack_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS pack_payloads (
            pack_id TEXT NOT NULL PRIMARY KEY REFERENCES pack_activity(pack_id),
            payload BLOB NOT NULL
        ) WITHOUT ROWID
    ''')


def insert_pack(db: sqlite3.Connection, pack_id: str, payload: bytes) -> None:
    db.execute('INSERT INTO pack_payloads(pack_id, payload) VALUES (?, ?)', (pack_id, payload))


def read_pack_bytes(db: sqlite3.Connection, pack_id: str) -> bytes | None:
    row = db.execute('SELECT payload FROM pack_payloads WHERE pack_id=?', (pack_id,)).fetchone()
    return None if row is None else row[0]


def load_entry(db: sqlite3.Connection, address: PackAddress) -> PackEntry | None:
    validate_pack_address(address)
    payload = read_pack_bytes(db, address.pack_id)
    if payload is None:
        return None
    entries = decode_pack(payload)
    if address.slot >= len(entries):
        return None
    return entries[address.slot]


def remove_pack_payload(db: sqlite3.Connection, pack_id: str) -> None:
    result = db.execute('DELETE FROM pack_payloads WHERE pack_id=?', (pack_id,))
    if result.rowcount != 1:
        raise PackStoreError(f'missing active payload for {pack_id}')

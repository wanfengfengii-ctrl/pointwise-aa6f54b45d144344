from collections.abc import Iterable
from dataclasses import dataclass
import sqlite3

from packing.addresses import PackAddress, validate_pack_address
from packing.format import FullEntry, PackFormatError, decode_pack, encode_pack


@dataclass(frozen=True, slots=True)
class ReplacementBinding:
    original: PackAddress
    entry: FullEntry


def create_replacement_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS replacement_payloads (
            payload_id INTEGER PRIMARY KEY,
            payload BLOB NOT NULL
        )
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS replacement_bindings (
            original_pack TEXT NOT NULL REFERENCES pack_activity(pack_id),
            original_slot INTEGER NOT NULL CHECK (original_slot >= 0),
            payload_id INTEGER NOT NULL UNIQUE REFERENCES replacement_payloads(payload_id),
            PRIMARY KEY (original_pack, original_slot)
        ) WITHOUT ROWID
    ''')


def stage_replacements(db: sqlite3.Connection, bindings: Iterable[ReplacementBinding]) -> None:
    if not db.in_transaction:
        raise sqlite3.ProgrammingError('replacement staging requires a transaction')
    for binding in bindings:
        validate_pack_address(binding.original)
        if not isinstance(binding.entry, FullEntry):
            raise PackFormatError('replacement must hold a complete entry')
        result = db.execute(
            'INSERT INTO replacement_payloads(payload) VALUES (?)', (encode_pack((binding.entry,)),),
        )
        db.execute('''
            INSERT INTO replacement_bindings(original_pack, original_slot, payload_id)
            VALUES (?, ?, ?)
        ''', (binding.original.pack_id, binding.original.slot, result.lastrowid))


def get_replacement_entry(db: sqlite3.Connection, original: PackAddress) -> FullEntry | None:
    validate_pack_address(original)
    row = db.execute('''
        SELECT payloads.payload FROM replacement_bindings AS bindings
        JOIN replacement_payloads AS payloads USING (payload_id)
        WHERE bindings.original_pack=? AND bindings.original_slot=?
    ''', (original.pack_id, original.slot)).fetchone()
    if row is None:
        return None
    entries = decode_pack(row[0])
    if len(entries) != 1 or not isinstance(entries[0], FullEntry):
        raise PackFormatError('invalid replacement payload')
    return entries[0]

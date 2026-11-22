import sqlite3

from maintenance.replacement import get_replacement_entry
from packing.addresses import PackAddress
from packing.chains import IncompleteEvidence
from packing.format import PackEntry
from packing.store import load_entry


class MissingEntry(IncompleteEvidence):
    pass


def resolve_entry(db: sqlite3.Connection, address: PackAddress) -> PackEntry:
    entry = load_entry(db, address)
    if entry is None:
        entry = get_replacement_entry(db, address)
    if entry is None:
        raise MissingEntry(f'no readable evidence for {address.pack_id}:{address.slot}')
    return entry

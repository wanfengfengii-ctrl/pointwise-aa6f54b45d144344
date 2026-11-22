import sqlite3

from packing.addresses import PackAddress, validate_pack_address


class PackActivityError(ValueError):
    pass


def create_activity_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS pack_activity (
            pack_id TEXT NOT NULL PRIMARY KEY,
            active INTEGER NOT NULL CHECK (active IN (0, 1))
        ) WITHOUT ROWID
    ''')


def register_active_pack(db: sqlite3.Connection, pack_id: str) -> None:
    validate_pack_address(PackAddress(pack_id, 0))
    result = db.execute('''
        INSERT INTO pack_activity(pack_id, active) VALUES (?, 1)
        ON CONFLICT(pack_id) DO NOTHING
    ''', (pack_id,))
    if result.rowcount != 1:
        raise PackActivityError(f'pack id already allocated: {pack_id}')


def require_active_pack(db: sqlite3.Connection, pack_id: str) -> None:
    validate_pack_address(PackAddress(pack_id, 0))
    row = db.execute('SELECT active FROM pack_activity WHERE pack_id=?', (pack_id,)).fetchone()
    if row is None or row[0] != 1:
        raise PackActivityError(f'pack is not active: {pack_id}')


def mark_pack_retired(db: sqlite3.Connection, pack_id: str) -> None:
    result = db.execute('UPDATE pack_activity SET active=0 WHERE pack_id=? AND active=1', (pack_id,))
    if result.rowcount != 1:
        raise PackActivityError(f'pack is not active: {pack_id}')


def list_active_packs(db: sqlite3.Connection) -> tuple[str, ...]:
    return tuple(row[0] for row in db.execute('SELECT pack_id FROM pack_activity WHERE active=1 ORDER BY pack_id'))

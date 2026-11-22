import sqlite3

from ingest.records import Observation, RevisionKey


def create_ingest_schema(db: sqlite3.Connection) -> None:
    db.execute('''
        CREATE TABLE IF NOT EXISTS revisions (
            source TEXT NOT NULL,
            record_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            value BLOB NOT NULL,
            PRIMARY KEY (source, record_id, revision_id)
        ) WITHOUT ROWID
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS batches (
            source TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            PRIMARY KEY (source, batch_id)
        ) WITHOUT ROWID
    ''')
    db.execute('''
        CREATE TABLE IF NOT EXISTS batch_items (
            source TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            position INTEGER NOT NULL CHECK (position >= 0),
            record_id TEXT NOT NULL,
            revision_id TEXT NOT NULL,
            PRIMARY KEY (source, batch_id, position),
            FOREIGN KEY (source, batch_id) REFERENCES batches(source, batch_id),
            FOREIGN KEY (source, record_id, revision_id)
                REFERENCES revisions(source, record_id, revision_id)
        ) WITHOUT ROWID
    ''')


def find_revision(db: sqlite3.Connection, key: RevisionKey) -> bytes | None:
    row = db.execute(
        'SELECT value FROM revisions WHERE source=? AND record_id=? AND revision_id=?',
        (key.source, key.record, key.revision),
    ).fetchone()
    return None if row is None else row[0]


def insert_revisions(db: sqlite3.Connection, observations: tuple[Observation, ...]) -> None:
    db.executemany(
        'INSERT INTO revisions(source, record_id, revision_id, value) VALUES (?, ?, ?, ?)',
        ((item.key.source, item.key.record, item.key.revision, item.value)
         for item in observations),
    )


def load_batch_acceptance(
    db: sqlite3.Connection, source: str, batch_id: str,
) -> tuple[Observation, ...] | None:
    if db.execute(
        'SELECT 1 FROM batches WHERE source=? AND batch_id=?', (source, batch_id),
    ).fetchone() is None:
        return None
    rows = db.execute('''
        SELECT items.record_id, items.revision_id, revisions.value
        FROM batch_items AS items
        JOIN revisions USING (source, record_id, revision_id)
        WHERE items.source=? AND items.batch_id=?
        ORDER BY items.position
    ''', (source, batch_id))
    return tuple(Observation(RevisionKey(source, record, revision), value)
                 for record, revision, value in rows)


def store_batch_acceptance(
    db: sqlite3.Connection, source: str, batch_id: str, keys: tuple[RevisionKey, ...],
) -> None:
    if any(key.source != source for key in keys):
        raise ValueError('batch item belongs to another source')
    db.execute('INSERT INTO batches(source, batch_id) VALUES (?, ?)', (source, batch_id))
    db.executemany('''
        INSERT INTO batch_items(source, batch_id, position, record_id, revision_id)
        VALUES (?, ?, ?, ?, ?)
    ''', ((source, batch_id, position, key.record, key.revision)
          for position, key in enumerate(keys)))

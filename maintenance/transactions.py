from collections.abc import Iterator
from contextlib import contextmanager
from os import PathLike
import sqlite3

from ingest.catalog import create_ingest_schema
from maintenance.active import create_activity_schema
from maintenance.receipts import create_retirement_receipt_schema
from maintenance.replacement import create_replacement_schema
from packing.store import create_pack_schema
from snapshot.catalog import create_snapshot_schema
from snapshot.receipts import create_publication_receipt_schema


def open_database(path: str | PathLike[str]) -> sqlite3.Connection:
    db = sqlite3.connect(path, isolation_level=None)
    try:
        db.execute('PRAGMA foreign_keys = ON')
    except BaseException:
        db.close()
        raise
    return db


@contextmanager
def _transaction(db: sqlite3.Connection, begin: str) -> Iterator[sqlite3.Connection]:
    db.execute(begin)
    try:
        yield db
        db.commit()
    except BaseException:
        if db.in_transaction:
            db.rollback()
        raise


def read_transaction(db: sqlite3.Connection):
    return _transaction(db, 'BEGIN')


def write_transaction(db: sqlite3.Connection):
    return _transaction(db, 'BEGIN IMMEDIATE')


def initialize_database(db: sqlite3.Connection) -> None:
    with write_transaction(db):
        create_ingest_schema(db)
        create_activity_schema(db)
        create_pack_schema(db)
        create_snapshot_schema(db)
        create_publication_receipt_schema(db)
        create_replacement_schema(db)
        create_retirement_receipt_schema(db)

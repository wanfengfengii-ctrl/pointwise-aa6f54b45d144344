from contextlib import closing
from pathlib import Path
import sqlite3

from ingest.batches import BatchSubmission, accept_batch
from ingest.records import Observation, RevisionKey
from maintenance.retire import retire_pack
from maintenance.transactions import initialize_database, open_database
from packing.addresses import PackAddress
from packing.seal import SealSelection, seal_pack
from packing.store import read_pack_bytes
from reading.open import read_snapshot
from snapshot.catalog import get_manifest_bytes
from snapshot.publish import publish_snapshot
from snapshot.receipts import load_publication_receipt


_LEGACY_SQL = Path(__file__).resolve().parent / "samples" / "legacy-contributions.sql"


def _revision(record):
    return RevisionKey("station", record, "v1")


def build_chain(db, base_slot=0):
    observations = tuple(Observation(_revision(record), value) for record, value in (
        ("left", b"AB"), ("right", b"AB"), ("ax", b"Ax"),
        ("axbang", b"Ax!"), ("short", b"A"), ("empty", b""),
    ))
    accept_batch(db, BatchSubmission("station", "early", observations))
    left, right, empty = seal_pack(db, "P", tuple(
        SealSelection(_revision(record)) for record in ("left", "right", "empty")
    )).addresses
    q, = seal_pack(db, "Q", (SealSelection(_revision("ax"), (left, right)[base_slot], 1),)).addresses
    r, = seal_pack(db, "R", (SealSelection(_revision("axbang"), q, 2),)).addresses
    short, = seal_pack(db, "S", (SealSelection(_revision("short"), r, 1),)).addresses
    return r, short, empty, r


def load_v1_database(db):
    db.executescript(_LEGACY_SQL.read_text(encoding="utf-8"))
    if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise AssertionError("legacy database contains a broken binding")


def seal_legacy_descendants(db):
    base = PackAddress("Q", 0)
    return seal_pack(db, "S", (
        SealSelection(_revision("positive"), base, 1),
        SealSelection(_revision("fresh"), base, 0),
        SealSelection(_revision("empty"), base, 0),
    )).addresses


def install_publication_commit_fault(db):
    db.executescript("""
        CREATE TABLE fixture_publication_parent(id INTEGER PRIMARY KEY);
        CREATE TABLE fixture_publication_child(
            parent_id INTEGER REFERENCES fixture_publication_parent(id) DEFERRABLE INITIALLY DEFERRED
        );
        CREATE TRIGGER fixture_publication_fault AFTER INSERT ON publication_receipts
        BEGIN
            INSERT INTO fixture_publication_child(parent_id) VALUES (1);
        END;
    """)


def _v1_round(base_slot):
    with closing(open_database(":memory:")) as db:
        initialize_database(db)
        selection = build_chain(db, base_slot)
        result = publish_snapshot(db, "close", selection)
        publish_snapshot(db, "sources", (PackAddress("P", 0), PackAddress("P", 1)))
        q_payload = read_pack_bytes(db, "Q")
        for pack in ("P", "Q"):
            retire_pack(db, pack)
            assert read_pack_bytes(db, pack) is None
            audit = read_snapshot(db, result.manifest)
            assert tuple(row.value for row in audit.rows) == (b"Ax!", b"A", b"", b"Ax!")
        return q_payload, tuple(db.iterdump())


def main():
    left, right = _v1_round(0), _v1_round(1)
    assert left[0] != right[0] and left[1] == right[1]
    print("V1_SAME_BYTES_ERASED_SOURCE")
    with closing(open_database(":memory:")) as db:
        load_v1_database(db)
        initialize_database(db)
        assert read_pack_bytes(db, "Q") is None
        assert read_snapshot(db, "legacy").rows[0].value == b"Ax"
        selection = seal_legacy_descendants(db)
        result = publish_snapshot(db, "descendants", selection)
        assert tuple(row.value for row in read_snapshot(db, result.manifest).rows) == (b"Ay", b"\x00z", b"")
        install_publication_commit_fault(db)
        try:
            publish_snapshot(db, "retry", selection)
        except sqlite3.IntegrityError:
            assert not db.in_transaction
        else:
            raise AssertionError("the deferred foreign key did not fail")
        assert get_manifest_bytes(db, "retry") is None
        assert load_publication_receipt(db, "retry") is None
        assert not db.execute("SELECT * FROM fixture_publication_child").fetchall()
        db.execute("DROP TRIGGER fixture_publication_fault")
        assert publish_snapshot(db, "retry", selection).receipt.record_count == 3
    print("V1_LEGACY_AND_COMMIT_FIXTURES_OK")


if __name__ == "__main__":
    main()

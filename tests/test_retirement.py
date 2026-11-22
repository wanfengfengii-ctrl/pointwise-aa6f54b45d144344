import sqlite3

from ingest.records import RevisionKey
from maintenance.active import list_active_packs, mark_pack_retired
from maintenance.receipts import RetirementReceipt, load_retirement_receipt, save_retirement_receipt
from maintenance.replacement import ReplacementBinding, get_replacement_entry, stage_replacements
from maintenance.retire import RetirementError, retire_pack
from maintenance.transactions import write_transaction
from packing.addresses import PackAddress
from packing.format import FullEntry
from packing.seal import SealError, SealSelection, seal_pack
from packing.store import read_pack_bytes, remove_pack_payload
from reading.open import SnapshotReadError, read_snapshot
from snapshot.catalog import get_manifest_bytes
from snapshot.publish import publish_snapshot
from tests.support import LakeCase


class RetirementTests(LakeCase):
    def _assert_saved_reads(self, direct, indirect):
        rows = read_snapshot(self.db, direct.manifest).rows
        self.assertEqual([(r.address, r.revision, r.value, r.byte_length) for r in rows], [
            (PackAddress('P', 1), RevisionKey('station', 'reference', 'v1'), b'CD', 2),
        ])
        rows = read_snapshot(self.db, indirect.manifest).rows
        self.assertEqual([(r.address, r.revision, r.value, r.byte_length) for r in rows], [
            (PackAddress('R', 0), RevisionKey('station', 'signal', 'v3'), b'Ax!', 3),
        ])

    def _storage_state(self):
        return (
            list_active_packs(self.db),
            self.db.execute('SELECT pack_id, payload FROM pack_payloads ORDER BY pack_id').fetchall(),
            self.db.execute('SELECT payload_id, payload FROM replacement_payloads ORDER BY payload_id').fetchall(),
            self.db.execute('SELECT original_pack, original_slot, payload_id FROM replacement_bindings ORDER BY 1, 2').fetchall(),
            self.db.execute('SELECT * FROM retirement_receipts ORDER BY pack_id').fetchall(),
        )

    def test_joint_retirement(self):
        direct, indirect = self.workday_snapshots()
        originals = {name: read_pack_bytes(self.db, name) for name in ('P', 'Q', 'R')}
        receipt = retire_pack(self.db, 'P')
        self.reopen()
        self._assert_saved_reads(direct, indirect)
        self.assertEqual(get_manifest_bytes(self.db, 'reference'), direct.manifest)
        self.assertEqual(get_manifest_bytes(self.db, 'signal'), indirect.manifest)
        self.assertEqual(list_active_packs(self.db), ('Q', 'R'))
        self.assertIsNone(read_pack_bytes(self.db, 'P'))
        self.assertEqual(read_pack_bytes(self.db, 'Q'), originals['Q'])
        self.assertEqual(read_pack_bytes(self.db, 'R'), originals['R'])
        self.assertEqual(receipt.pack_id, 'P')
        self.assertEqual(receipt.removed_bytes, len(originals['P']))
        self.assertEqual(load_retirement_receipt(self.db, 'P'), receipt)
        self.assertEqual(publish_snapshot(self.db, 'reference', (PackAddress('P', 1),)), direct)
        with self.assertRaises(SealError):
            seal_pack(self.db, 'P', ())
        for name in ('P', 'unknown'):
            with self.assertRaises(RetirementError):
                retire_pack(self.db, name)
        self.assertEqual(load_retirement_receipt(self.db, 'P'), receipt)

    def test_preplaced_replacement_read(self):
        direct, indirect = self.workday_snapshots()
        original = read_pack_bytes(self.db, 'P')
        with write_transaction(self.db):
            stage_replacements(self.db, (
                ReplacementBinding(PackAddress('P', 0), FullEntry(RevisionKey('station', 'signal', 'v1'), b'AB')),
                ReplacementBinding(PackAddress('P', 1), FullEntry(RevisionKey('station', 'reference', 'v1'), b'CD')),
            ))
            remove_pack_payload(self.db, 'P')
            mark_pack_retired(self.db, 'P')
            save_retirement_receipt(self.db, RetirementReceipt('P', len(original), 2))
        self.reopen()
        self.assertIsNone(read_pack_bytes(self.db, 'P'))
        self._assert_saved_reads(direct, indirect)

    def test_repeated_retirement_preserves_published_chain(self):
        direct, indirect = self.workday_snapshots()
        retire_pack(self.db, 'P')
        q0 = PackAddress('Q', 0)
        later = self.submit('later', ('signal', 'v4', b'Ax?')).revisions[0]
        sealed = seal_pack(self.db, 'S', (SealSelection(later, q0, 2),))
        extra = publish_snapshot(self.db, 'later-shift', sealed.addresses)
        retire_pack(self.db, 'Q')
        self.reopen()
        self._assert_saved_reads(direct, indirect)
        self.assertEqual(read_snapshot(self.db, extra.manifest).rows[0].value, b'Ax?')
        self.assertEqual(list_active_packs(self.db), ('R', 'S'))
        self.assertIsNone(read_pack_bytes(self.db, 'Q'))

    def test_retire_pack_with_an_unpublished_unreadable_slot(self):
        base, pinned, unused = self.submit('morning', (
            'base', 'v1', b'AB'), ('pinned', 'v1', b'CD'), ('unused', 'v1', b'AX'),
        ).revisions
        first, = seal_pack(self.db, 'X', (SealSelection(base),)).addresses
        keep, drop = seal_pack(self.db, 'P', (SealSelection(pinned), SealSelection(unused, first, 1))).addresses
        fixed = publish_snapshot(self.db, 'fixed', (keep,))
        retire_pack(self.db, 'X')
        with self.assertRaisesRegex(SnapshotReadError, 'X:0'):
            # Keep the candidate selection unpublished when checking its lost base.
            read_snapshot(self.db, self._unreadable_fixture_manifest(drop, unused))
        retire_pack(self.db, 'P')
        self.reopen()
        self.assertEqual(read_snapshot(self.db, fixed.manifest).rows[0].value, b'CD')
        self.assertIsNone(read_pack_bytes(self.db, 'P'))
        self.assertIsNone(get_replacement_entry(self.db, drop))

    def _unreadable_fixture_manifest(self, address, revision):
        from reading.reconstruct import reconstruct_entry
        from packing.chains import IncompleteEvidence

        try:
            reconstruct_entry(self.db, address, revision)
        except IncompleteEvidence as exc:
            raise SnapshotReadError(str(exc)) from exc
        self.fail('unpublished slot unexpectedly kept its base')

    def test_stage_rollback_and_retry(self):
        direct, indirect = self.workday_snapshots()
        self.db.execute('CREATE TABLE commit_parents(id INTEGER PRIMARY KEY)')
        self.db.execute('''
            CREATE TABLE commit_evidence (
                parent_id INTEGER REFERENCES commit_parents(id) DEFERRABLE INITIALLY DEFERRED
            )
        ''')
        before = self._storage_state()
        reached_commit_boundary = []

        def fail_commit(connection):
            self.assertIs(connection, self.db)
            self.assertIsNone(read_pack_bytes(connection, 'P'))
            self.assertIsNotNone(get_replacement_entry(connection, PackAddress('P', 1)))
            self.assertIsNotNone(load_retirement_receipt(connection, 'P'))
            connection.execute('INSERT INTO commit_evidence(parent_id) VALUES (1)')
            reached_commit_boundary.append(True)

        with self.assertRaises(RetirementError) as failure:
            retire_pack(self.db, 'P', _before_commit=fail_commit)
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(reached_commit_boundary, [True])
        self.reopen()
        self.assertEqual(self._storage_state(), before)
        self.assertEqual(self.db.execute('SELECT * FROM commit_evidence').fetchall(), [])
        self._assert_saved_reads(direct, indirect)
        receipt = retire_pack(self.db, 'P')
        self.reopen()
        self.assertEqual(load_retirement_receipt(self.db, 'P'), receipt)
        self.assertIsNone(read_pack_bytes(self.db, 'P'))
        self._assert_saved_reads(direct, indirect)

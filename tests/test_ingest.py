from ingest.batches import BatchSubmission, accept_batch
from ingest.catalog import find_revision, load_batch_acceptance
from ingest.records import InvalidObservation, Observation, RevisionKey
from ingest.revisions import RevisionConflict
from packing.seal import SealSelection, seal_pack
from reading.open import read_snapshot
from snapshot.publish import publish_snapshot
from tests.support import LakeCase


class IngestTests(LakeCase):
    def test_replay_and_correction(self):
        row = ('signal', 'v1', b'AB')
        first = self.submit('early', row, row)
        self.assertEqual(first.new_revisions, 1)
        self.assertEqual(first.revisions, (RevisionKey('station', 'signal', 'v1'),) * 2)
        self.reopen()
        replay = self.submit('early', row, row)
        self.assertEqual(replay.revisions, first.revisions)
        self.assertEqual(replay.new_revisions, 0)
        self.assertEqual(self.submit('repeat', row).new_revisions, 0)
        correction = self.submit('correction', ('signal', 'v2', b'AX'))
        self.assertEqual(correction.new_revisions, 1)
        with self.assertRaises(RevisionConflict):
            self.submit('early', row)
        sealed = seal_pack(self.db, 'P', tuple(SealSelection(key) for key in (
            first.revisions[0], correction.revisions[0],
        )))
        publish_snapshot(self.db, 'morning', sealed.addresses)
        self.assertEqual([row.value for row in read_snapshot(self.db, 'morning').rows], [b'AB', b'AX'])
        self.assertEqual(load_batch_acceptance(self.db, 'station', 'early'), (
            Observation(first.revisions[0], b'AB'), Observation(first.revisions[0], b'AB'),
        ))

    def test_source_isolation(self):
        left = self.submit('early', ('r1', 'v1', b'AB'), source='A').revisions[0]
        right = self.submit('early', ('r1', 'v1', b'CD'), source='B').revisions[0]
        self.assertEqual(find_revision(self.db, left), b'AB')
        self.assertEqual(find_revision(self.db, right), b'CD')
        pack = seal_pack(self.db, 'P', (SealSelection(right), SealSelection(left)))
        publish_snapshot(self.db, 'handoff', pack.addresses)
        rows = read_snapshot(self.db, 'handoff').rows
        self.assertEqual([(row.revision.source, row.value) for row in rows], [('B', b'CD'), ('A', b'AB')])

    def test_batch_conflict_atomic(self):
        original = self.submit('early', ('r1', 'v1', b'AB')).revisions[0]
        with self.assertRaises(RevisionConflict):
            self.submit('bad', ('r2', 'v1', b'CD'), ('r1', 'v1', b'AX'))
        with self.assertRaises(RevisionConflict):
            self.submit('within', ('r3', 'v1', b''), ('r3', 'v1', b'D'))
        self.reopen()
        self.assertEqual(find_revision(self.db, original), b'AB')
        for record in ('r2', 'r3'):
            self.assertIsNone(find_revision(self.db, RevisionKey('station', record, 'v1')))
        for batch in ('bad', 'within'):
            self.assertIsNone(load_batch_acceptance(self.db, 'station', batch))
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0], 1)
        self.assertEqual(load_batch_acceptance(self.db, 'station', 'early'), (Observation(original, b'AB'),))

    def test_invalid_batch_is_rejected(self):
        with self.assertRaises(InvalidObservation):
            self.submit('early', ('r1', 'v1', b'AB'), ('bad/id', 'v1', b'CD'))
        with self.assertRaises(InvalidObservation):
            accept_batch(self.db, BatchSubmission('A', 'early', (Observation(RevisionKey('B', 'r1', 'v1'), b'AB'),)))
        self.assertIsNone(load_batch_acceptance(self.db, 'station', 'early'))
        self.assertIsNone(find_revision(self.db, RevisionKey('station', 'r1', 'v1')))

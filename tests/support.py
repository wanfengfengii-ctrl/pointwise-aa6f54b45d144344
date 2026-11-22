from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ingest.batches import BatchSubmission, accept_batch
from ingest.records import Observation, RevisionKey
from maintenance.transactions import initialize_database, open_database
from packing.seal import SealSelection, seal_pack
from snapshot.publish import publish_snapshot


class LakeCase(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='chengchuan-test-'))
        self.path = Path(directory) / 'lake.sqlite3'
        self.db = open_database(self.path)
        self.addCleanup(self._close_database)
        initialize_database(self.db)

    def _close_database(self):
        self.db.close()

    def reopen(self):
        self.db.close()
        self.db = open_database(self.path)

    def submit(self, batch_id, *rows, source='station'):
        observations = tuple(Observation(RevisionKey(source, record, revision), value)
                             for record, revision, value in rows)
        return accept_batch(self.db, BatchSubmission(source, batch_id, observations))

    def workday_chain(self):
        ab, cd, ax, ax_bang = self.submit(
            'morning', ('signal', 'v1', b'AB'), ('reference', 'v1', b'CD'),
            ('signal', 'v2', b'Ax'), ('signal', 'v3', b'Ax!'),
        ).revisions
        first = seal_pack(self.db, 'P', (SealSelection(ab), SealSelection(cd)))
        second = seal_pack(self.db, 'Q', (SealSelection(ax, first.addresses[0], 1),))
        third = seal_pack(self.db, 'R', (SealSelection(ax_bang, second.addresses[0], 2),))
        return first, second, third

    def workday_snapshots(self):
        first, _, third = self.workday_chain()
        direct = publish_snapshot(self.db, 'reference', (first.addresses[1],))
        indirect = publish_snapshot(self.db, 'signal', third.addresses)
        return direct, indirect

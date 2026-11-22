from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from contribution_examples import (
    build_chain, install_publication_commit_fault, load_v1_database, seal_legacy_descendants,
)
from ingest.batches import BatchSubmission, accept_batch
from ingest.records import Observation, RevisionKey
from maintenance.retire import retire_pack
from maintenance.transactions import initialize_database, open_database
from packing.seal import SealSelection, seal_pack
from packing.store import read_pack_bytes
from reading.open import (
    MissingContributionEvidence, SnapshotReadError, read_contributions, read_snapshot,
)
from snapshot.catalog import get_manifest_bytes
from snapshot.contributions import is_contribution_snapshot
from snapshot.publish import PublicationError, publish_snapshot, publish_with_contributions
from snapshot.receipts import load_publication_receipt
from tests.support import LakeCase


def _spans(row):
    return [(start, end, (key.source, key.record, key.revision), s, e)
            for start, end, key, s, e in row.contributions]


class ContributionReadTests(LakeCase):
    def _published(self, base_slot):
        return publish_with_contributions(self.db, 'close', build_chain(self.db, base_slot))

    def test_two_bases_attribute_first_byte(self):
        with closing(open_database(':memory:')) as db:
            initialize_database(db)
            left = publish_with_contributions(db, 'close', build_chain(db, 0))
            left_rows = read_contributions(db, left.manifest).rows
        self.assertEqual([row.position for row in left_rows], [0, 1, 2, 3])
        self.assertEqual([row.value for row in left_rows], [b'Ax!', b'A', b'', b'Ax!'])
        self.assertEqual(_spans(left_rows[0]), [
            (0, 1, ('station', 'left', 'v1'), 0, 1),
            (1, 2, ('station', 'ax', 'v1'), 1, 2),
            (2, 3, ('station', 'axbang', 'v1'), 2, 3),
        ])
        self.assertEqual(_spans(left_rows[1]), [(0, 1, ('station', 'left', 'v1'), 0, 1)])
        self.assertEqual(left_rows[2].contributions, ())
        self.assertEqual(left_rows[0].contributions, left_rows[3].contributions)
        self.assertEqual(left.receipt.record_count, 4)
        self.assertEqual(left.receipt.total_bytes, 7)

        with closing(open_database(':memory:')) as db:
            initialize_database(db)
            right = publish_with_contributions(db, 'close', build_chain(db, 1))
            right_rows = read_contributions(db, right.manifest).rows
        self.assertEqual(_spans(right_rows[0])[0], (0, 1, ('station', 'right', 'v1'), 0, 1))
        self.assertEqual(_spans(right_rows[1]), [(0, 1, ('station', 'right', 'v1'), 0, 1)])
        self.assertEqual(_spans(right_rows[0])[1:], _spans(left_rows[0])[1:])

    def test_adjacent_same_source_merges(self):
        accept_batch(self.db, BatchSubmission('station', 'early', (
            Observation(RevisionKey('station', 'left', 'v1'), b'AB'),
            Observation(RevisionKey('station', 'right', 'v1'), b'AB'),
        )))
        left, _ = seal_pack(self.db, 'P', (
            SealSelection(RevisionKey('station', 'left', 'v1')),
            SealSelection(RevisionKey('station', 'right', 'v1')),
        )).addresses
        top, = seal_pack(self.db, 'T', (
            SealSelection(RevisionKey('station', 'left', 'v1'), left, 1),
        )).addresses
        result = publish_with_contributions(self.db, 'merged', (top,))
        row = read_contributions(self.db, result.manifest).rows[0]
        self.assertEqual(_spans(row), [(0, 2, ('station', 'left', 'v1'), 0, 2)])

    def test_plain_snapshot_has_no_contributions(self):
        key = self.submit('early', ('a', 'v1', b'AB')).revisions[0]
        address, = seal_pack(self.db, 'P', (SealSelection(key),)).addresses
        published = publish_snapshot(self.db, 'plain', (address,))
        with self.assertRaises(MissingContributionEvidence):
            read_contributions(self.db, 'plain')
        with self.assertRaises(MissingContributionEvidence):
            read_contributions(self.db, published.manifest)

    def test_unknown_and_bad_selector_rejected(self):
        key = self.submit('early', ('a', 'v1', b'AB')).revisions[0]
        address, = seal_pack(self.db, 'P', (SealSelection(key),)).addresses
        published = publish_snapshot(self.db, 'plain', (address,))
        for selector in ('unknown', published.manifest + b' ', b'not json'):
            with self.subTest(selector=selector):
                with self.assertRaises(SnapshotReadError):
                    read_contributions(self.db, selector)


class ContributionPublishTests(LakeCase):
    def test_replay_and_mode_conflict(self):
        selection = build_chain(self.db, 0)
        result = publish_with_contributions(self.db, 'close', selection)
        self.reopen()
        self.assertEqual(publish_with_contributions(self.db, 'close', list(selection)), result)
        with self.assertRaises(PublicationError):
            publish_with_contributions(self.db, 'close', selection[::-1])
        with self.assertRaises(PublicationError):
            publish_snapshot(self.db, 'close', selection)
        publish_snapshot(self.db, 'plain', (selection[2],))
        with self.assertRaises(PublicationError):
            publish_with_contributions(self.db, 'plain', (selection[2],))
        self.assertEqual([row.value for row in read_snapshot(self.db, result.manifest).rows],
                         [b'Ax!', b'A', b'', b'Ax!'])

    def test_retirement_and_reopen_preserve_provenance(self):
        result = publish_with_contributions(self.db, 'close', build_chain(self.db, 0))
        before = read_contributions(self.db, result.manifest)
        for pack in ('P', 'Q'):
            retire_pack(self.db, pack)
            self.assertIsNone(read_pack_bytes(self.db, pack))
            self.assertEqual(read_contributions(self.db, result.manifest), before)
        self.reopen()
        self.assertEqual(read_contributions(self.db, result.manifest), before)
        self.assertEqual(read_contributions(self.db, 'close'), before)
        self.assertEqual([row.value for row in read_snapshot(self.db, result.manifest).rows],
                         [b'Ax!', b'A', b'', b'Ax!'])

    def test_tampered_evidence_rejected_wholesale(self):
        result = publish_with_contributions(self.db, 'close', build_chain(self.db, 0))
        self.db.execute(
            'UPDATE contribution_spans SET out_end=out_end+1 '
            'WHERE snapshot_id=? AND position=0 AND ordinal=0', ('close',),
        )
        self.reopen()
        with self.assertRaises(SnapshotReadError):
            read_contributions(self.db, result.manifest)
        self.db.execute(
            'DELETE FROM contribution_spans WHERE snapshot_id=? AND position=0 AND ordinal=2',
            ('close',),
        )
        with self.assertRaises(SnapshotReadError):
            read_contributions(self.db, result.manifest)


class LegacyContributionTests(LakeCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory(prefix='chengchuan-legacy-'))
        path = Path(directory) / 'legacy.sqlite3'
        self.db = open_database(path)
        self.addCleanup(self.db.close)
        load_v1_database(self.db)
        initialize_database(self.db)

    def test_legacy_plain_read_and_missing_contributions(self):
        self.assertIsNone(read_pack_bytes(self.db, 'Q'))
        self.assertEqual(read_snapshot(self.db, 'legacy').rows[0].value, b'Ax')
        with self.assertRaises(MissingContributionEvidence):
            read_contributions(self.db, 'legacy')

    def test_unknown_prefix_rejected_zero_prefix_published(self):
        selection = seal_legacy_descendants(self.db)
        with self.assertRaises(PublicationError):
            publish_with_contributions(self.db, 'descendants', selection)
        self.assertIsNone(get_manifest_bytes(self.db, 'descendants'))
        self.assertFalse(is_contribution_snapshot(self.db, 'descendants'))
        result = publish_with_contributions(self.db, 'fresh', (selection[1], selection[2]))
        rows = read_contributions(self.db, result.manifest).rows
        self.assertEqual([row.value for row in rows], [b'\x00z', b''])
        self.assertEqual(_spans(rows[0]), [(0, 2, ('station', 'fresh', 'v1'), 0, 2)])
        self.assertEqual(rows[1].contributions, ())

    def test_broken_zero_prefix_base_chain_rejected(self):
        selection = seal_legacy_descendants(self.db)
        self.db.execute(
            'DELETE FROM replacement_bindings WHERE original_pack=? AND original_slot=?', ('Q', 0),
        )
        with self.assertRaises(PublicationError):
            publish_with_contributions(self.db, 'fresh', (selection[1], selection[2]))
        self.assertIsNone(get_manifest_bytes(self.db, 'fresh'))

    def test_commit_failure_leaves_no_partial_publication(self):
        selection = seal_legacy_descendants(self.db)
        install_publication_commit_fault(self.db)
        with self.assertRaises(PublicationError) as failure:
            publish_with_contributions(self.db, 'retry', (selection[1], selection[2]))
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertFalse(self.db.in_transaction)
        self.assertIsNone(get_manifest_bytes(self.db, 'retry'))
        self.assertIsNone(load_publication_receipt(self.db, 'retry'))
        self.assertFalse(is_contribution_snapshot(self.db, 'retry'))
        self.db.execute('DROP TRIGGER fixture_publication_fault')
        result = publish_with_contributions(self.db, 'retry', (selection[1], selection[2]))
        self.assertEqual(result.receipt.record_count, 2)
        self.assertEqual(read_contributions(self.db, result.manifest).rows[0].value, b'\x00z')

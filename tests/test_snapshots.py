import hashlib

from packing.addresses import PackAddress
from packing.seal import SealSelection, seal_pack
from reading.open import SnapshotReadError, open_snapshot, read_snapshot
from snapshot.catalog import get_manifest_bytes
from snapshot.publish import PublicationError, publish_snapshot
from snapshot.receipts import load_publication_receipt
from tests.support import LakeCase


class SnapshotTests(LakeCase):
    def test_ordered_repeat_empty_and_reopen(self):
        empty, signal = self.submit('early', ('empty', 'v1', b''), ('signal', 'v1', b'AB')).revisions
        first, second = seal_pack(self.db, 'P', (SealSelection(empty), SealSelection(signal))).addresses
        result = publish_snapshot(self.db, 'handoff', (second, first, second))
        self.submit('correction', ('signal', 'v2', b'AX'))
        self.reopen()
        manifest = open_snapshot(self.db, result.manifest)
        self.assertEqual([item.address for item in manifest.entries], [second, first, second])
        self.assertEqual([item.revision for item in manifest.entries], [signal, empty, signal])
        read = read_snapshot(self.db, result.manifest)
        self.assertEqual(read, read_snapshot(self.db, 'handoff'))
        self.assertEqual([(r.position, r.address, r.revision, r.value, r.byte_length) for r in read.rows], [
            (0, second, signal, b'AB', 2), (1, first, empty, b'', 0), (2, second, signal, b'AB', 2),
        ])
        self.assertEqual(read.total_bytes, 4)
        self.assertEqual(result.receipt.record_count, 3)
        self.assertEqual(result.receipt.total_bytes, 4)

    def test_snapshot_replay_and_conflict(self):
        a, b = self.submit('early', ('a', 'v1', b'AB'), ('b', 'v1', b'CD')).revisions
        chosen = seal_pack(self.db, 'P', (SealSelection(a), SealSelection(b))).addresses
        result = publish_snapshot(self.db, 'handoff', chosen)
        self.reopen()
        self.assertEqual(publish_snapshot(self.db, 'handoff', list(chosen)), result)
        with self.assertRaises(PublicationError):
            publish_snapshot(self.db, 'handoff', chosen[::-1])
        self.assertEqual(get_manifest_bytes(self.db, 'handoff'), result.manifest)
        receipt = load_publication_receipt(self.db, 'handoff')
        self.assertEqual(receipt, result.receipt)
        self.assertEqual(receipt.manifest_sha256, hashlib.sha256(result.manifest).hexdigest())

    def test_missing_tail_no_publication_or_receipt(self):
        key = self.submit('early', ('a', 'v1', b'AB')).revisions[0]
        addresses = seal_pack(self.db, 'P', (SealSelection(key),)).addresses
        old = publish_snapshot(self.db, 'old', addresses)
        with self.assertRaises(PublicationError):
            publish_snapshot(self.db, 'incomplete', addresses + (PackAddress('P', 1),))
        self.reopen()
        self.assertIsNone(get_manifest_bytes(self.db, 'incomplete'))
        self.assertIsNone(load_publication_receipt(self.db, 'incomplete'))
        with self.assertRaises(SnapshotReadError):
            read_snapshot(self.db, 'incomplete')
        self.assertEqual(read_snapshot(self.db, old.manifest).rows[0].value, b'AB')

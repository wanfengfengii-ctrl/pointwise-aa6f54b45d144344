import hashlib

from packing.chains import IncompleteEvidence, materialize_value
from packing.addresses import PackAddress
from packing.format import DeltaEntry, FullEntry, PackFormatError, decode_pack, encode_pack
from packing.seal import SealSelection, seal_pack
from reading.open import SnapshotReadError, read_snapshot
from snapshot.manifest import ManifestEntry, SnapshotManifest, serialize_manifest
from snapshot.publish import publish_snapshot
from tests.support import LakeCase


class EvidenceTests(LakeCase):
    def test_incomplete_read_has_no_partial_result(self):
        first, _, third = self.workday_chain()
        good = publish_snapshot(self.db, 'good', (first.addresses[1],))
        fixed = publish_snapshot(self.db, 'fixed', (first.addresses[1], third.addresses[0]))
        self.db.execute('DELETE FROM pack_payloads WHERE pack_id=?', ('Q',))
        self.reopen()
        with self.assertRaisesRegex(SnapshotReadError, 'Q:0'):
            read_snapshot(self.db, fixed.manifest)
        self.assertEqual([r.value for r in read_snapshot(self.db, good.manifest).rows], [b'CD'])

    def test_manifest_must_match_published_evidence(self):
        a, b = self.submit('early', ('a', 'v1', b'AB'), ('b', 'v1', b'CD')).revisions
        first, second = seal_pack(self.db, 'P', (SealSelection(a), SealSelection(b))).addresses
        valid = publish_snapshot(self.db, 'fixed', (first,))
        different = serialize_manifest(SnapshotManifest('fixed', (ManifestEntry(second, b),)))
        with self.assertRaises(SnapshotReadError):
            read_snapshot(self.db, different)
        with self.assertRaises(SnapshotReadError):
            read_snapshot(self.db, valid.manifest + b' ')
        self.db.execute('UPDATE pack_payloads SET payload=? WHERE pack_id=?', (encode_pack((FullEntry(b, b'CD'),)), 'P'))
        with self.assertRaisesRegex(SnapshotReadError, 'revision'):
            read_snapshot(self.db, valid.manifest)

    def test_pack_detects_modified_and_truncated_evidence(self):
        key = self.submit('early', ('a', 'v1', b'\xff\x00')).revisions[0]
        raw = encode_pack((FullEntry(key, b'\xff\x00'),))
        entries = decode_pack(raw)
        self.assertEqual(entries, (FullEntry(key, b'\xff\x00'),))
        tampered = raw[:-1] + bytes([raw[-1] ^ 1])
        body = raw[:-33]
        truncated_frame = body + hashlib.sha256(body).digest()
        for bad in (tampered, raw[:4], truncated_frame):
            with self.subTest(bad=bad.hex()):
                with self.assertRaises(PackFormatError):
                    decode_pack(bad)

    def test_chain_rejects_cycles_and_invalid_prefix_evidence(self):
        key = self.submit('early', ('a', 'v1', b'AB')).revisions[0]
        a, b = PackAddress('P', 0), PackAddress('Q', 0)
        entries = {a: DeltaEntry(key, b, 1, b'x'), b: DeltaEntry(key, a, 1, b'y')}
        with self.assertRaisesRegex(IncompleteEvidence, 'cycle'):
            materialize_value(a, entries.get)
        entries[b] = FullEntry(key, b'')
        with self.assertRaisesRegex(IncompleteEvidence, 'invalid delta'):
            materialize_value(a, entries.get)

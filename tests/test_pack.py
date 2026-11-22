from ingest.records import RevisionKey
from maintenance.active import list_active_packs
from packing.addresses import PackAddress
from packing.format import DeltaEntry, FullEntry, decode_pack
from packing.seal import SealError, SealSelection, seal_pack
from packing.store import read_pack_bytes
from reading.open import read_snapshot
from snapshot.publish import publish_snapshot
from tests.support import LakeCase


class PackTests(LakeCase):
    def test_full_pack_and_address_scope(self):
        a, b = self.submit('early', ('r1', 'v1', b'AB'), ('r2', 'v1', b'CD')).revisions
        first = seal_pack(self.db, 'P', (SealSelection(a), SealSelection(b)))
        second = seal_pack(self.db, 'Q', (SealSelection(b),))
        self.assertEqual(first.addresses, (PackAddress('P', 0), PackAddress('P', 1)))
        self.assertEqual(second.addresses, (PackAddress('Q', 0),))
        self.assertEqual(list_active_packs(self.db), ('P', 'Q'))
        raw = read_pack_bytes(self.db, 'P')
        self.assertEqual(first.sealed_bytes, len(raw))
        self.assertEqual(decode_pack(raw), (FullEntry(a, b'AB'), FullEntry(b, b'CD')))
        publish_snapshot(self.db, 'addresses', (second.addresses[0], first.addresses[0], first.addresses[1]))
        self.assertEqual([r.value for r in read_snapshot(self.db, 'addresses').rows], [b'CD', b'AB', b'CD'])

    def test_two_hop_delta(self):
        first, second, third = self.workday_chain()
        q, = decode_pack(read_pack_bytes(self.db, 'Q'))
        r, = decode_pack(read_pack_bytes(self.db, 'R'))
        self.assertEqual(q, DeltaEntry(RevisionKey('station', 'signal', 'v2'), first.addresses[0], 1, b'x'))
        self.assertEqual(r, DeltaEntry(RevisionKey('station', 'signal', 'v3'), second.addresses[0], 2, b'!'))
        published = publish_snapshot(self.db, 'handoff', second.addresses + third.addresses)
        self.assertEqual(published.receipt.total_bytes, 5)
        rows = read_snapshot(self.db, published.manifest).rows
        self.assertEqual([(r.value, r.byte_length) for r in rows], [(b'Ax', 2), (b'Ax!', 3)])

    def test_binary_prefix_and_empty_suffix(self):
        base, unrelated, empty = self.submit(
            'early', ('base', 'v1', b'\x00\xff'), ('other', 'v1', b'\xfe\x00'), ('empty', 'v1', b''),
        ).revisions
        first, = seal_pack(self.db, 'P', (SealSelection(base),)).addresses
        packed = seal_pack(self.db, 'Q', (
            SealSelection(unrelated, first, 0), SealSelection(base, first, 2), SealSelection(empty, first, 0),
        ))
        self.assertEqual(tuple(entry.suffix for entry in decode_pack(read_pack_bytes(self.db, 'Q'))),
                         (b'\xfe\x00', b'', b''))
        publish_snapshot(self.db, 'binary', packed.addresses)
        rows = read_snapshot(self.db, 'binary').rows
        self.assertEqual([(r.value, r.byte_length) for r in rows], [(b'\xfe\x00', 2), (b'\x00\xff', 2), (b'', 0)])

    def test_reject_invalid_pack_atomically(self):
        base, mismatch = self.submit('early', ('r1', 'v1', b'AB'), ('r2', 'v1', b'XB')).revisions
        address, = seal_pack(self.db, 'P', (SealSelection(base),)).addresses
        original = read_pack_bytes(self.db, 'P')
        bad = (
            SealSelection(base, address, 3), SealSelection(mismatch, address, 1),
            SealSelection(base, PackAddress('P', 9), 0),
            SealSelection(RevisionKey('station', 'r1', 'v0')), SealSelection(base, address, True),
        )
        for selection in bad:
            with self.subTest(selection=selection):
                with self.assertRaises(SealError):
                    seal_pack(self.db, 'Q', (SealSelection(base), selection))
                self.assertIsNone(read_pack_bytes(self.db, 'Q'))
                self.assertEqual(list_active_packs(self.db), ('P',))
                self.assertEqual(read_pack_bytes(self.db, 'P'), original)
        with self.assertRaises(SealError):
            seal_pack(self.db, 'P', (SealSelection(mismatch),))
        self.assertEqual(read_pack_bytes(self.db, 'P'), original)

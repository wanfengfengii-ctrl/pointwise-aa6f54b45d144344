from ingest.catalog import find_revision
from maintenance.active import list_active_packs
from maintenance.receipts import load_retirement_receipt
from maintenance.retire import retire_pack
from maintenance.transactions import initialize_database
from packing.seal import SealSelection, seal_pack
from packing.store import read_pack_bytes
from reading.open import read_snapshot
from snapshot.publish import publish_snapshot
from snapshot.receipts import load_publication_receipt
from tests.support import LakeCase


class InitializationTests(LakeCase):
    def test_initialize_again_preserves_user_data(self):
        key = self.submit('odd-day', ('gauge', 'v9', b'\x01\xff')).revisions[0]
        pack = seal_pack(self.db, 'user-pack', (SealSelection(key),))
        published = publish_snapshot(self.db, 'user-shift', pack.addresses)
        retired = retire_pack(self.db, 'user-pack')
        self.reopen()
        initialize_database(self.db)
        initialize_database(self.db)
        self.assertEqual(find_revision(self.db, key), b'\x01\xff')
        self.assertEqual(self.submit('odd-day', ('gauge', 'v9', b'\x01\xff')).new_revisions, 0)
        self.assertEqual(load_publication_receipt(self.db, 'user-shift'), published.receipt)
        self.assertEqual(load_retirement_receipt(self.db, 'user-pack'), retired)
        self.assertEqual(list_active_packs(self.db), ())
        self.assertIsNone(read_pack_bytes(self.db, 'user-pack'))
        self.assertEqual(read_snapshot(self.db, published.manifest).rows[0].value, b'\x01\xff')

    def test_empty_ordered_inputs_have_stable_results(self):
        self.assertEqual(self.submit('empty').revisions, ())
        self.assertEqual(self.submit('empty').new_revisions, 0)
        pack = seal_pack(self.db, 'empty-pack', ())
        published = publish_snapshot(self.db, 'empty-shift', pack.addresses)
        self.assertEqual(published.receipt.record_count, 0)
        self.assertEqual(retire_pack(self.db, 'empty-pack').preserved_addresses, 0)
        self.reopen()
        self.assertEqual(read_snapshot(self.db, published.manifest).rows, ())

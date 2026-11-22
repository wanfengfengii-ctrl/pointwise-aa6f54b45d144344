from collections.abc import Callable
import sqlite3

from maintenance.active import PackActivityError, mark_pack_retired, require_active_pack
from maintenance.dependencies import collect_retirement_dependencies
from maintenance.receipts import RetirementReceipt, save_retirement_receipt
from maintenance.replacement import ReplacementBinding, stage_replacements
from maintenance.transactions import write_transaction
from packing.addresses import InvalidPackAddress
from packing.chains import IncompleteEvidence
from packing.format import FullEntry, PackFormatError
from packing.store import PackStoreError, read_pack_bytes, remove_pack_payload
from reading.reconstruct import reconstruct_entry
from snapshot.manifest import ManifestError


class RetirementError(ValueError):
    pass


def retire_pack(
    db: sqlite3.Connection, pack_id: str, *,
    _before_commit: Callable[[sqlite3.Connection], None] | None = None,
) -> RetirementReceipt:
    try:
        with write_transaction(db):
            require_active_pack(db, pack_id)
            payload = read_pack_bytes(db, pack_id)
            if payload is None:
                raise PackStoreError(f'missing active payload for {pack_id}')
            dependencies = collect_retirement_dependencies(db, pack_id)
            bindings = []
            for address in dependencies.addresses:
                restored = reconstruct_entry(db, address)
                bindings.append(ReplacementBinding(address, FullEntry(restored.revision, restored.value)))
            stage_replacements(db, bindings)
            remove_pack_payload(db, pack_id)
            mark_pack_retired(db, pack_id)
            receipt = RetirementReceipt(pack_id, len(payload), len(bindings))
            save_retirement_receipt(db, receipt)
            if _before_commit is not None:
                _before_commit(db)
            return receipt
    except (InvalidPackAddress, PackActivityError, PackStoreError, PackFormatError,
            IncompleteEvidence, ManifestError, sqlite3.Error) as exc:
        raise RetirementError(f'cannot retire {pack_id!r}: {exc}') from exc

from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3

from ingest.catalog import find_revision
from ingest.records import InvalidObservation, RevisionKey, validate_identifier, validate_revision_key
from maintenance.active import PackActivityError, register_active_pack
from maintenance.transactions import write_transaction
from packing.addresses import InvalidPackAddress, PackAddress, validate_pack_address
from packing.chains import IncompleteEvidence, materialize_value
from packing.delta import InvalidPrefix, make_prefix_delta
from packing.format import DeltaEntry, FullEntry, PackEntry, PackFormatError, encode_pack
from packing.store import insert_pack
from reading.resolve import resolve_entry


class SealError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SealSelection:
    revision: RevisionKey
    base: PackAddress | None = None
    prefix: int = 0


@dataclass(frozen=True, slots=True)
class SealResult:
    pack_id: str
    addresses: tuple[PackAddress, ...]
    sealed_bytes: int


def _prepare_entry(db: sqlite3.Connection, selection: SealSelection) -> PackEntry:
    if not isinstance(selection, SealSelection):
        raise SealError('expected a SealSelection')
    validate_revision_key(selection.revision)
    value = find_revision(db, selection.revision)
    if value is None:
        raise SealError(f'unknown revision {selection.revision!r}')
    if selection.base is None:
        if type(selection.prefix) is not int or selection.prefix != 0:
            raise SealError('a prefix requires a base address')
        return FullEntry(selection.revision, value)
    validate_pack_address(selection.base)
    base = materialize_value(selection.base, lambda address: resolve_entry(db, address))
    suffix = make_prefix_delta(base.value, value, selection.prefix)
    return DeltaEntry(selection.revision, selection.base, selection.prefix, suffix)


def seal_pack(
    db: sqlite3.Connection, pack_id: str, selections: Sequence[SealSelection],
) -> SealResult:
    try:
        validate_identifier(pack_id, 'pack id')
        try:
            ordered = tuple(selections)
        except TypeError as exc:
            raise SealError('expected ordered pack selections') from exc
        with write_transaction(db):
            entries = tuple(_prepare_entry(db, selection) for selection in ordered)
            payload = encode_pack(entries)
            register_active_pack(db, pack_id)
            insert_pack(db, pack_id, payload)
            addresses = tuple(PackAddress(pack_id, slot) for slot in range(len(entries)))
            return SealResult(pack_id, addresses, len(payload))
    except (InvalidObservation, InvalidPackAddress, InvalidPrefix, IncompleteEvidence,
            PackFormatError, PackActivityError) as exc:
        raise SealError(f'cannot seal {pack_id!r}: {exc}') from exc

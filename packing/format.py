from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import struct

from ingest.records import InvalidObservation, RevisionKey, validate_revision_key
from packing.addresses import InvalidPackAddress, PackAddress, validate_pack_address


_MAGIC = b'CCPACK\x01'
_U32 = struct.Struct('>I')
_U64 = struct.Struct('>Q')
_DIGEST_SIZE = hashlib.sha256().digest_size


class PackFormatError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FullEntry:
    revision: RevisionKey
    value: bytes


@dataclass(frozen=True, slots=True)
class DeltaEntry:
    revision: RevisionKey
    base: PackAddress
    prefix: int
    suffix: bytes


PackEntry = FullEntry | DeltaEntry


def _frame(value: bytes) -> bytes:
    if not isinstance(value, bytes):
        raise PackFormatError('expected bytes in pack field')
    return _U32.pack(len(value)) + value


def _encode_entry(entry: PackEntry) -> bytes:
    if not isinstance(entry, (FullEntry, DeltaEntry)):
        raise PackFormatError('unknown entry type')
    validate_revision_key(entry.revision)
    identity = b''.join(_frame(text.encode('ascii')) for text in (
        entry.revision.source, entry.revision.record, entry.revision.revision,
    ))
    if isinstance(entry, FullEntry):
        return b'F' + identity + _frame(entry.value)
    validate_pack_address(entry.base)
    if type(entry.prefix) is not int or not 0 <= entry.prefix < 1 << 64:
        raise PackFormatError('prefix outside encoded integer range')
    return b''.join((
        b'D', identity, _frame(entry.base.pack_id.encode('ascii')),
        _U64.pack(entry.base.slot), _U64.pack(entry.prefix), _frame(entry.suffix),
    ))


def encode_pack(entries: Sequence[PackEntry]) -> bytes:
    try:
        body = _MAGIC + _U32.pack(len(entries)) + b''.join(_encode_entry(item) for item in entries)
    except (struct.error, InvalidObservation, InvalidPackAddress) as exc:
        raise PackFormatError(f'invalid pack field: {exc}') from exc
    return body + hashlib.sha256(body).digest()


class _Cursor:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if end > len(self.data):
            raise PackFormatError('truncated pack field')
        part = self.data[self.position:end]
        self.position = end
        return part

    def number(self, encoding: struct.Struct) -> int:
        return encoding.unpack(self.take(encoding.size))[0]

    def frame(self) -> bytes:
        return self.take(self.number(_U32))

    def identifier(self) -> str:
        return self.frame().decode('ascii')


def _decode_entry(cursor: _Cursor) -> PackEntry:
    tag = cursor.take(1)
    if tag not in (b'F', b'D'):
        raise PackFormatError('unknown pack entry marker')
    revision = RevisionKey(cursor.identifier(), cursor.identifier(), cursor.identifier())
    validate_revision_key(revision)
    if tag == b'F':
        return FullEntry(revision, cursor.frame())
    base = PackAddress(cursor.identifier(), cursor.number(_U64))
    validate_pack_address(base)
    return DeltaEntry(revision, base, cursor.number(_U64), cursor.frame())


def decode_pack(payload: bytes) -> tuple[PackEntry, ...]:
    if not isinstance(payload, bytes) or len(payload) < len(_MAGIC) + _U32.size + _DIGEST_SIZE:
        raise PackFormatError('truncated pack')
    body, digest = payload[:-_DIGEST_SIZE], payload[-_DIGEST_SIZE:]
    if hashlib.sha256(body).digest() != digest:
        raise PackFormatError('pack checksum mismatch')
    cursor = _Cursor(body)
    if cursor.take(len(_MAGIC)) != _MAGIC:
        raise PackFormatError('unsupported pack header')
    try:
        count = cursor.number(_U32)
        entries = tuple(_decode_entry(cursor) for _ in range(count))
    except (UnicodeDecodeError, InvalidObservation, InvalidPackAddress) as exc:
        raise PackFormatError(f'invalid pack identity: {exc}') from exc
    if cursor.position != len(body):
        raise PackFormatError('unexpected trailing pack bytes')
    return entries

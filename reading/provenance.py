from dataclasses import dataclass
import sqlite3

from ingest.records import RevisionKey
from maintenance.replacement import get_replacement_entry
from packing.addresses import InvalidPackAddress, PackAddress
from packing.chains import IncompleteEvidence
from packing.delta import InvalidPrefix, apply_prefix_delta
from packing.format import DeltaEntry, FullEntry, PackFormatError
from packing.store import load_entry


@dataclass(frozen=True, slots=True)
class ContributionSpan:
    """A single output range attributed to one source revision.

    ``source`` is ``None`` when the bytes are readable but their provenance is
    not recorded (legacy replacement payloads).  Unknown spans mirror their
    output offsets in ``source_start``/``source_end`` so clipping stays simple.
    """

    out_start: int
    out_end: int
    source: RevisionKey | None
    source_start: int
    source_end: int

    @property
    def byte_length(self) -> int:
        return self.out_end - self.out_start

    def as_public(self) -> tuple[int, int, RevisionKey, int, int]:
        if self.source is None:
            raise IncompleteEvidence('contribution evidence has no source revision')
        return (self.out_start, self.out_end, self.source,
                self.source_start, self.source_end)


@dataclass(frozen=True, slots=True)
class ProvenanceRecord:
    revision: RevisionKey
    value: bytes
    spans: tuple[ContributionSpan, ...]
    complete: bool


def _entry_with_origin(
    db: sqlite3.Connection, address: PackAddress,
) -> tuple[FullEntry | DeltaEntry, bool]:
    """Return the entry at ``address`` and whether it is a retired replacement."""
    entry = load_entry(db, address)
    if entry is not None:
        return entry, False
    replacement = get_replacement_entry(db, address)
    if replacement is None:
        raise IncompleteEvidence(f'no readable evidence for {address.pack_id}:{address.slot}')
    return replacement, True


def _known_spans(value: bytes, revision: RevisionKey) -> list[ContributionSpan]:
    if not value:
        return []
    return [ContributionSpan(0, len(value), revision, 0, len(value))]


def _unknown_spans(value: bytes) -> list[ContributionSpan]:
    if not value:
        return []
    return [ContributionSpan(0, len(value), None, 0, len(value))]


def _clip_spans(spans: list[ContributionSpan], limit: int) -> list[ContributionSpan]:
    clipped = []
    for span in spans:
        start = max(span.out_start, 0)
        end = min(span.out_end, limit)
        if start >= end:
            continue
        offset = start - span.out_start
        clipped.append(ContributionSpan(
            start, end, span.source,
            span.source_start + offset, span.source_start + (end - span.out_start),
        ))
    return clipped


def _merge_spans(spans: list[ContributionSpan]) -> list[ContributionSpan]:
    merged: list[ContributionSpan] = []
    for span in spans:
        if merged:
            last = merged[-1]
            if (last.out_end == span.out_start and last.source == span.source
                    and last.source_end == span.source_start):
                merged[-1] = ContributionSpan(
                    last.out_start, span.out_end, last.source,
                    last.source_start, span.source_end,
                )
                continue
        merged.append(span)
    return merged


def materialize_contributions(
    db: sqlite3.Connection, address: PackAddress,
) -> ProvenanceRecord:
    """Restore an address and attribute every output byte to its source."""
    steps: list[tuple[PackAddress, DeltaEntry]] = []
    seen: set[PackAddress] = set()
    current = address
    while current not in seen:
        seen.add(current)
        try:
            entry, replaced = _entry_with_origin(db, current)
        except (InvalidPackAddress, PackFormatError) as exc:
            raise IncompleteEvidence(f'invalid pack evidence at {current!r}') from exc
        if isinstance(entry, FullEntry):
            value = entry.value
            revision = entry.revision
            spans = _unknown_spans(value) if replaced else _known_spans(value, revision)
            break
        if not isinstance(entry, DeltaEntry):
            raise IncompleteEvidence(f'missing pack evidence at {current!r}')
        steps.append((current, entry))
        current = entry.base
    else:
        raise IncompleteEvidence(f'cycle at {current!r}')

    for position, delta in reversed(steps):
        try:
            value = apply_prefix_delta(value, delta.prefix, delta.suffix)
        except InvalidPrefix as exc:
            raise IncompleteEvidence(f'invalid delta at {position!r}') from exc
        spans = _clip_spans(spans, delta.prefix)
        if delta.suffix:
            start = delta.prefix
            end = start + len(delta.suffix)
            spans.append(ContributionSpan(start, end, delta.revision, start, end))
        spans = _merge_spans(spans)
        revision = delta.revision
    return ProvenanceRecord(
        revision, value, tuple(spans), all(span.source is not None for span in spans),
    )

from collections.abc import Callable

from packing.addresses import InvalidPackAddress, PackAddress
from packing.delta import InvalidPrefix, apply_prefix_delta
from packing.format import DeltaEntry, FullEntry, PackEntry, PackFormatError


class IncompleteEvidence(ValueError):
    pass


def materialize_value(
    address: PackAddress, fetch: Callable[[PackAddress], PackEntry | None],
) -> FullEntry:
    steps: list[tuple[PackAddress, DeltaEntry]] = []
    seen: set[PackAddress] = set()
    current = address
    while current not in seen:
        seen.add(current)
        try:
            entry = fetch(current)
        except (InvalidPackAddress, PackFormatError) as exc:
            raise IncompleteEvidence(f'invalid pack evidence at {current!r}') from exc
        if isinstance(entry, FullEntry):
            value = entry.value
            revision = entry.revision
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
        revision = delta.revision
    return FullEntry(revision, value)

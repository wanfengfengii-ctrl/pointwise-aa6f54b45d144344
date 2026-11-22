from collections.abc import Callable
from dataclasses import dataclass

from ingest.records import Observation, RevisionKey


class RevisionConflict(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RevisionDecision:
    observation: Observation
    is_new: bool


def reconcile_revisions(
    observations: tuple[Observation, ...], lookup: Callable[[RevisionKey], bytes | None],
) -> tuple[RevisionDecision, ...]:
    seen: dict[RevisionKey, bytes] = {}
    decisions = []
    for item in observations:
        existing = seen[item.key] if item.key in seen else lookup(item.key)
        if existing is not None and existing != item.value:
            raise RevisionConflict(f'different bytes for revision {item.key!r}')
        decisions.append(RevisionDecision(item, existing is None))
        seen[item.key] = item.value
    return tuple(decisions)

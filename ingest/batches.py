from collections.abc import Sequence
from dataclasses import dataclass
import sqlite3

from ingest.catalog import (
    find_revision, insert_revisions, load_batch_acceptance, store_batch_acceptance,
)
from ingest.records import (
    InvalidObservation, Observation, RevisionKey, validate_identifier, validate_observation,
)
from ingest.revisions import RevisionConflict, reconcile_revisions
from maintenance.transactions import write_transaction


@dataclass(frozen=True, slots=True)
class BatchSubmission:
    source: str
    batch_id: str
    observations: Sequence[Observation]


@dataclass(frozen=True, slots=True)
class BatchAcceptance:
    source: str
    batch_id: str
    revisions: tuple[RevisionKey, ...]
    new_revisions: int


def accept_batch(db: sqlite3.Connection, submission: BatchSubmission) -> BatchAcceptance:
    if not isinstance(submission, BatchSubmission):
        raise InvalidObservation('expected a BatchSubmission')
    source, batch_id = submission.source, submission.batch_id
    validate_identifier(source, 'source')
    validate_identifier(batch_id, 'batch id')
    try:
        observations = tuple(submission.observations)
    except TypeError as exc:
        raise InvalidObservation('expected ordered observations') from exc
    for observation in observations:
        validate_observation(observation)
        if observation.key.source != source:
            raise InvalidObservation('observation source differs from batch source')
    keys = tuple(item.key for item in observations)

    with write_transaction(db):
        previous = load_batch_acceptance(db, source, batch_id)
        if previous is not None:
            if previous != observations:
                raise RevisionConflict(f'different input for batch {source}/{batch_id}')
            return BatchAcceptance(source, batch_id, keys, 0)
        decisions = reconcile_revisions(observations, lambda key: find_revision(db, key))
        additions = tuple(item.observation for item in decisions if item.is_new)
        insert_revisions(db, additions)
        store_batch_acceptance(db, source, batch_id, keys)
        return BatchAcceptance(source, batch_id, keys, len(additions))

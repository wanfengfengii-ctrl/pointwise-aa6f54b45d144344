from dataclasses import dataclass
import re


_IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}')


class InvalidObservation(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RevisionKey:
    source: str
    record: str
    revision: str


@dataclass(frozen=True, slots=True)
class Observation:
    key: RevisionKey
    value: bytes


def validate_identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise InvalidObservation(f'invalid {field}: {value!r}')


def validate_revision_key(key: RevisionKey) -> None:
    if not isinstance(key, RevisionKey):
        raise InvalidObservation('expected a RevisionKey')
    validate_identifier(key.source, 'source')
    validate_identifier(key.record, 'record')
    validate_identifier(key.revision, 'revision')


def validate_observation(observation: Observation) -> None:
    if not isinstance(observation, Observation):
        raise InvalidObservation('expected an Observation')
    validate_revision_key(observation.key)
    if not isinstance(observation.value, bytes):
        raise InvalidObservation('observation value must be bytes')

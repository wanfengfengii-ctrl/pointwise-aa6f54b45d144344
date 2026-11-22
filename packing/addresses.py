from dataclasses import dataclass

from ingest.records import InvalidObservation, validate_identifier


MAX_SLOT = (1 << 63) - 1


class InvalidPackAddress(ValueError):
    pass


@dataclass(frozen=True, order=True, slots=True)
class PackAddress:
    pack_id: str
    slot: int


def validate_pack_address(address: PackAddress) -> None:
    if not isinstance(address, PackAddress):
        raise InvalidPackAddress('expected a PackAddress')
    try:
        validate_identifier(address.pack_id, 'pack id')
    except InvalidObservation as exc:
        raise InvalidPackAddress(str(exc)) from exc
    if type(address.slot) is not int or not 0 <= address.slot <= MAX_SLOT:
        raise InvalidPackAddress(f'invalid pack slot: {address.slot!r}')

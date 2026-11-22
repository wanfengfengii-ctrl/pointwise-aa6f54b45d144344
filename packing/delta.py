class InvalidPrefix(ValueError):
    pass


def _check_prefix(base: bytes, prefix: int) -> None:
    if type(prefix) is not int or not 0 <= prefix <= len(base):
        raise InvalidPrefix(f'prefix {prefix!r} outside 0..{len(base)} bytes')


def make_prefix_delta(base: bytes, target: bytes, prefix: int) -> bytes:
    _check_prefix(base, prefix)
    if base[:prefix] != target[:prefix]:
        raise InvalidPrefix('target and base prefixes differ')
    return target[prefix:]


def apply_prefix_delta(base: bytes, prefix: int, suffix: bytes) -> bytes:
    _check_prefix(base, prefix)
    return base[:prefix] + suffix

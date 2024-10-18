from enum import Enum


def _repr(dct: dict, _names):
    try:
        return " | ".join((item.name if isinstance(item := dct.pop(n), Enum) else str(item)) for n in _names)
    except KeyError:
        return dct["id"]

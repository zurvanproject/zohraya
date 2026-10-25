"""Unambiguous JSON decoding for external proposal-history files.

Decode before schema/hash checks: a normal dict can no longer reveal keys that
the JSON decoder silently overwrote. Preserve accepted values without repair.
"""
import json
import math


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + repr(key))
        result[key] = value
    return result


def _constant(token):
    raise ValueError('non-finite JSON number: ' + token)


def _float(token):
    value = float(token)
    if not math.isfinite(value):
        raise ValueError('non-finite JSON number: ' + token)
    return value


def loads(text):
    """Reject duplicate keys, non-JSON constants and overflow to infinity."""
    return json.loads(text, object_pairs_hook=_object,
                      parse_constant=_constant, parse_float=_float)

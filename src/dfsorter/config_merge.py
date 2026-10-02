"""Three-way merge of packaged game defaults and editable game definitions."""

from copy import deepcopy

MISSING = object()


def _same(left, right):
    return left == right if left is not MISSING and right is not MISSING else left is right


def _copy(value):
    return MISSING if value is MISSING else deepcopy(value)


def _path(parts):
    return ".".join(str(part) for part in parts)


def _reordered(base, current):
    shared = [item for item in base if item in current]
    return shared != [item for item in current if item in base]


def _removed_items(base, current):
    return {item for item in base if item not in current}


def _merge_list(base, local, incoming, path, conflicts):
    if _same(local, incoming) or _same(incoming, base):
        return _copy(local)
    if _same(local, base):
        return _copy(incoming)
    if all(isinstance(value, str) for items in (base, local, incoming) for value in items):
        if _reordered(base, local) and _reordered(base, incoming) and local != incoming:
            conflicts.append(_path(path))
            return _copy(local)
        if _removed_items(base, local) != _removed_items(base, incoming):
            conflicts.append(_path(path))
            return _copy(local)
        merged = [value for value in local if value in incoming or value not in base]
        additions = [value for value in incoming if value not in base and value not in merged]
        if merged and merged[-1] == "mainline":
            merged[-1:-1] = additions
        else:
            merged.extend(additions)
        return merged
    conflicts.append(_path(path))
    return _copy(local)


def merge(base, local, incoming, path=(), conflicts=None):
    """Return merged data, preserving local values at conflicting paths."""
    if conflicts is None:
        conflicts = []
    if _same(local, incoming) or _same(incoming, base):
        return _copy(local)
    if _same(local, base):
        return _copy(incoming)
    if isinstance(local, dict) and isinstance(incoming, dict) and (
        isinstance(base, dict) or base is MISSING
    ):
        previous = base if isinstance(base, dict) else {}
        result = _copy(local)
        for key in dict.fromkeys([*previous, *local, *incoming]):
            value = merge(
                previous.get(key, MISSING), local.get(key, MISSING),
                incoming.get(key, MISSING), (*path, key), conflicts,
            )
            if value is MISSING:
                result.pop(key, None)
            else:
                result[key] = value
        return result
    if all(isinstance(value, list) for value in (base, local, incoming)):
        return _merge_list(base, local, incoming, path, conflicts)
    conflicts.append(_path(path))
    return _copy(local)


def _changes(local, desired, path=()):
    if local == desired:
        return
    if isinstance(local, dict) and isinstance(desired, dict):
        for key in dict.fromkeys([*local, *desired]):
            if key not in desired:
                yield path + (key,), MISSING
            elif key not in local:
                yield path + (key,), _copy(desired[key])
            else:
                yield from _changes(local[key], desired[key], path + (key,))
    elif isinstance(local, list) and isinstance(desired, list) and all(
        isinstance(value, str) for value in [*local, *desired]
    ):
        if _reordered(local, desired):
            yield path, _copy(desired)
            return
        for value in local:
            if value not in desired:
                yield path + (value,), MISSING
        for value in desired:
            if value not in local:
                yield path + (value,), value
    else:
        yield path, _copy(desired)


def _apply_change(document, path, value):
    result = _copy(document)
    parent = result
    for part in path[:-1]:
        parent = parent[part]
    key = path[-1]
    if isinstance(parent, list):
        if value is MISSING:
            parent.remove(key)
        elif key not in parent:
            if parent and parent[-1] == "mainline":
                parent.insert(len(parent) - 1, value)
            else:
                parent.append(value)
    elif value is MISSING:
        parent.pop(key, None)
    else:
        parent[key] = value
    return result


def apply_valid_changes(local, desired, validate, conflicts):
    """Apply independent incoming changes, reporting those that break the schema."""
    pending = list(_changes(local, desired))
    result = _copy(local)
    while pending:
        remaining = []
        progressed = False
        for path, value in pending:
            candidate = _apply_change(result, path, value)
            try:
                validate(candidate)
            except (ValueError, TypeError):
                remaining.append((path, value))
            else:
                result = candidate
                progressed = True
        if not progressed:
            conflicts.extend(_path(path) for path, _value in remaining)
            break
        pending = remaining
    return result

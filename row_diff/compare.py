"""Streaming change detection over externally sorted CSV snapshots."""
from contextlib import contextmanager
from dataclasses import dataclass

from .snapshot import SnapshotError, sorted_snapshot


@dataclass(frozen=True)
class Change:
    kind: str
    key: tuple[str, ...]
    before: dict[str, str] | None
    after: dict[str, str] | None
    columns: tuple[str, ...]


@contextmanager
def compare_snapshots(before, after, keys, **sort_options):
    """Yield a lazy change iterator, sorted by textual key.

    Column order may differ; column sets must match exactly. Every value is
    compared literally, including whitespace and numeric-looking strings.
    Consume fully to validate duplicate keys on both sides. Earlier yielded
    changes are provisional until iteration succeeds; atomic report writing
    belongs to the caller. Neither input may change during this operation.
    """
    keys = tuple(keys)
    with sorted_snapshot(before, keys, **sort_options) as (old_header, old_rows):
        with sorted_snapshot(after, keys, **sort_options) as (new_header, new_rows):
            if set(old_header) != set(new_header):
                raise SnapshotError('snapshot column sets differ')
            columns = tuple(sorted(old_header))

            def named(header, row):
                values = dict(zip(header, row))
                return {column: values[column] for column in columns}

            def changes():
                old = next(old_rows, None)
                new = next(new_rows, None)
                while old is not None or new is not None:
                    if new is None or (old is not None and old[0] < new[0]):
                        yield Change('removed', old[0], named(old_header, old[1]), None, ())
                        old = next(old_rows, None)
                    elif old is None or new[0] < old[0]:
                        yield Change('added', new[0], None, named(new_header, new[1]), ())
                        new = next(new_rows, None)
                    else:
                        old_values = named(old_header, old[1])
                        new_values = named(new_header, new[1])
                        changed = tuple(c for c in columns if old_values[c] != new_values[c])
                        if changed:
                            yield Change('changed', old[0], old_values, new_values, changed)
                        old = next(old_rows, None)
                        new = next(new_rows, None)

            iterator = changes()
            try:
                yield iterator
            finally:
                iterator.close()

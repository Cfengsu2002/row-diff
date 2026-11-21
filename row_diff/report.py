"""Atomic publication of fully validated JSON Lines change reports."""
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

from .compare import compare_snapshots
from .snapshot import SnapshotError, file_signature


def write_report(before, after, keys, destination, **sort_options):
    """Return counts after fsync and same-directory atomic replacement.

    Earlier errors preserve existing output. Directory fsync and power-loss
    durability are not guaranteed. Concurrent writers use last-writer-wins.
    Inputs must not change during comparison. Output must not alias an input.
    """
    destination = Path(destination)
    for source in (before, after):
        source = Path(source)
        if (destination.resolve() == source.resolve() or
                (destination.exists() and os.path.samefile(destination, source))):
            raise ValueError('report destination must differ from input snapshots')
    signatures = [(source, file_signature(source)) for source in (before, after)]
    counts = dict.fromkeys(('added', 'removed', 'changed'), 0)
    staged = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         prefix='.row-diff-', suffix='.tmp',
                                         dir=destination.parent, delete=False) as handle:
            staged = Path(handle.name)
            with compare_snapshots(before, after, keys, **sort_options) as changes:
                for change in changes:
                    handle.write(json.dumps(asdict(change), ensure_ascii=False) + '\n')
                    counts[change.kind] += 1
            if any(file_signature(source) != signature for source, signature in signatures):
                raise SnapshotError('snapshot changed before report publication')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, destination)
        return counts
    finally:
        if staged is not None:
            staged.unlink(missing_ok=True)

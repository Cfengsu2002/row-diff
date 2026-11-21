"""Disk-backed ordering of CSV snapshots by explicit, textual keys."""
import csv
import heapq
import json
import stat
import tempfile
from contextlib import ExitStack, contextmanager
from pathlib import Path


class SnapshotError(ValueError):
    pass


def file_signature(source):
    info = Path(source).stat()
    if not stat.S_ISREG(info.st_mode):
        raise SnapshotError('snapshot must be a regular file')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _records(handle):
    for line in handle:
        key, row = json.loads(line)
        yield tuple(key), row


def _write_run(path, records):
    with path.open('w', encoding='utf-8', newline='') as handle:
        for key, row in records:
            handle.write(json.dumps([key, row], ensure_ascii=False) + '\n')


def _merge(paths):
    with ExitStack() as stack:
        readers = [stack.enter_context(p.open(encoding='utf-8')) for p in paths]
        yield from heapq.merge(*(_records(r) for r in readers), key=lambda item: item[0])


class _RunStore:
    """Compact full levels during ingestion to bound pending run metadata."""
    def __init__(self, root, fan_in):
        self.root, self.fan_in = root, fan_in
        self.levels = []
        self.serial = 0

    def write(self, records):
        path = self.root / f'run-{self.serial}.jsonl'
        self.serial += 1
        _write_run(path, records)
        level = 0
        while True:
            if level == len(self.levels):
                self.levels.append([])
            self.levels[level].append(path)
            if len(self.levels[level]) < self.fan_in:
                break
            group = self.levels[level]
            path = self.root / f'run-{self.serial}.jsonl'
            self.serial += 1
            _write_run(path, _merge(group))
            for old in group:
                old.unlink()
            self.levels[level] = []
            level += 1

    def paths(self):
        return [path for level in self.levels for path in level]


class _LimitedLines:
    def __init__(self, handle, limit):
        self.handle, self.limit, self.used = handle, limit, 0

    def __iter__(self):
        return self

    def __next__(self):
        line = self.handle.readline(self.limit - self.used + 1)
        if not line:
            raise StopIteration
        self.used += len(line)
        if self.used > self.limit:
            raise SnapshotError('CSV record exceeds character limit')
        return line

    def reset(self):
        self.used = 0


@contextmanager
def sorted_snapshot(source, keys, *, run_rows=10000, fan_in=32, temp_dir=None,
                    run_bytes=8 * 1024 * 1024, max_record_chars=1024 * 1024):
    """Yield (header, iterator); consume iterator inside the context.

    Key order is Python string order; values are never coerced to numbers.
    Runs obey row and estimated serialized UTF-8 byte budgets; a single
    record can exceed run_bytes. Python object overhead is additional memory; incremental compaction keeps
    pending run paths logarithmic in the number of initial runs. Logical CSV records include quoting and newlines
    in max_record_chars. The Python CSV field-size limit also applies. Duplicate keys fail when the iterator reaches them.
    """
    initial_signature = file_signature(source)
    keys = tuple(keys)
    if not keys or len(set(keys)) != len(keys):
        raise SnapshotError('keys must be nonempty and distinct')
    if type(run_rows) is not int or run_rows < 1:
        raise SnapshotError('run_rows must be a positive integer')
    if type(fan_in) is not int or fan_in < 2:
        raise SnapshotError('fan_in must be at least two')
    for name, value in (('run_bytes', run_bytes), ('max_record_chars', max_record_chars)):
        if type(value) is not int or value < 1:
            raise SnapshotError(f'{name} must be a positive integer')
    with tempfile.TemporaryDirectory(prefix='row-diff-', dir=temp_dir) as directory:
        root = Path(directory)
        store = _RunStore(root, fan_in)
        with open(source, encoding='utf-8-sig', newline='') as handle:
            lines = _LimitedLines(handle, max_record_chars)
            reader = csv.reader(lines, strict=True)
            try:
                header = next(reader)
            except StopIteration:
                raise SnapshotError('missing CSV header') from None
            if not header or any(not column for column in header) or len(set(header)) != len(header):
                raise SnapshotError('header names must be nonempty and distinct')
            if any(key not in header for key in keys):
                raise SnapshotError('key column missing from header')
            positions = [header.index(key) for key in keys]
            batch = []
            batch_bytes = 0
            lines.reset()
            for row in reader:
                lines.reset()
                if len(row) != len(header):
                    raise SnapshotError(f'wrong field count at CSV line {reader.line_num}')
                key = tuple(row[position] for position in positions)
                if any(value == '' for value in key):
                    raise SnapshotError(f'empty key at CSV line {reader.line_num}')
                record_bytes = len(json.dumps([key, row], ensure_ascii=False).encode('utf-8')) + 1
                if batch and batch_bytes + record_bytes > run_bytes:
                    store.write(sorted(batch, key=lambda item: item[0]))
                    batch = []
                    batch_bytes = 0
                batch.append((key, row))
                batch_bytes += record_bytes
                if len(batch) >= run_rows or batch_bytes >= run_bytes:
                    store.write(sorted(batch, key=lambda item: item[0]))
                    batch = []
                    batch_bytes = 0
            if batch:
                store.write(sorted(batch, key=lambda item: item[0]))
        if file_signature(source) != initial_signature:
            raise SnapshotError('snapshot changed while reading')
        paths = store.paths()
        generation = 0
        while len(paths) > fan_in:
            merged = []
            for start in range(0, len(paths), fan_in):
                group = paths[start:start + fan_in]
                path = root / f'merge-{generation}-{start}.jsonl'
                _write_run(path, _merge(group))
                merged.append(path)
                for old in group:
                    old.unlink()
            paths = merged
            generation += 1

        def unique_records():
            previous = None
            for key, row in _merge(paths):
                if key == previous:
                    raise SnapshotError('duplicate key in snapshot')
                previous = key
                yield key, row

        iterator = unique_records()
        try:
            yield tuple(header), iterator
        finally:
            iterator.close()

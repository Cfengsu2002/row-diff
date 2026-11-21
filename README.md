# row-diff

Compare two keyed CSV exports without loading either dataset into memory. Useful for checking a daily database export, a regenerated catalog, or a data migration: the report separates added, removed, and changed rows and includes the values on both sides.

## Run

Requires Python 3.11 or newer. There are no runtime dependencies.

```sh
python -m pip install .
row-diff before.csv after.csv --key account_id --output changes.jsonl
```

Repeat `--key` to use a composite key. Key order matters. A successful command prints counts such as `{"added": 1, "changed": 1, "removed": 0}`. Exit codes are 0 for a published report, 2 for invalid input/settings, 3 for storage/access failure, 130 for interruption, and 143 for SIGTERM.

```sh
row-diff examples/before.csv examples/after.csv \
  --key region --key id --output changes.jsonl
```

This example reports one changed account, one removal, and one addition. Each JSON Lines record contains `kind`, `key`, `before`, `after`, and `columns`. `columns` names the changed columns; it is empty for additions/removals. Missing sides are JSON null. Unchanged rows are omitted.

## Comparison rules

- UTF-8 CSV, optionally with a BOM. Standard comma-separated quoting and multiline values are supported.
- Each file needs distinct, nonempty column names and exactly the same column set. Column order may differ.
- Keys must be present, nonempty, and unique within each snapshot. Duplicate keys fail even when the repeated rows are identical.
- All values are literal strings: `01` differs from `1`, spaces are significant, and no numeric, date, null or Unicode normalization is performed.
- Reports are ordered by Python string comparison of the key tuple. Column names in reported values and changed-column lists are sorted.

## How it works

`sorted_snapshot` writes sorted runs to a private temporary directory. Full levels are merged during ingestion, so pending run-path metadata grows logarithmically with the number of runs. Merges open at most `fan_in` run readers. `compare_snapshots` then walks both sorted streams together.

The default run budget is 10,000 records or roughly 8 MiB of serialized UTF-8 data. These are not hard process-memory limits: Python objects, serialization buffers, merge heads, and temporary copies cost additional memory. One record may exceed the run byte budget. Logical CSV records are limited to 1,048,576 characters including quoting/newlines; Python's CSV field-size limit also applies. Change `--run-rows`, `--run-bytes`, `--fan-in`, `--max-record-chars`, or `--temp-dir` to suit the machine. Sorting needs temporary disk space and additional I/O for merge passes; there is no disk quota manager.

## Publication and failures

The CLI writes a staging file beside the destination, consumes the entire comparison, flushes and fsyncs the file, then atomically replaces the destination. Errors before replacement preserve an existing report. Newly published reports use the temporary file's restricted permissions; old destination permissions are not copied. Output must not alias an input through a path, symlink, or hardlink.

Inputs must be stable regular files. Device/inode/size/timestamp checks detect many edits and replacements, but are best-effort checks, not a lock or snapshot. A concurrent edit after the final check can escape detection. Copy exports to a stable location first. Concurrent report writers use last-writer-wins; parent directories must be trusted. Directory fsync is not performed, so power-loss durability is not guaranteed. SIGINT/SIGTERM normally clean staging files; SIGKILL or machine failure can leave temporary files. A signal racing with replacement may leave the new complete report in place.

Reports contain source values and may be sensitive. Nothing is uploaded. Store both scratch data and reports on appropriately protected local storage.

## Python API

```python
from row_diff import compare_snapshots, write_report

counts = write_report("before.csv", "after.csv", ["id"], "changes.jsonl")
with compare_snapshots("before.csv", "after.csv", ["id"]) as changes:
    for change in changes:
        print(change.kind, change.key)
```

Streaming changes are provisional until the iterator is fully consumed: a late duplicate can still fail the comparison. Use `write_report` when a consumer must never see a partial report. Keep streaming iteration inside the context manager so open files and scratch directories are cleaned up.

## Verify

```sh
python -m unittest discover -s tests -v
python examples/check_install.py
```

Tests cover external merges, randomized reference comparisons, quoted and Unicode values, duplicate tails, byte/record budgets, input mutation, atomic publication failures, and process signals. CI checks Python 3.11–3.14. AI tools assisted implementation and tests; the documented limits apply regardless of how code was produced.

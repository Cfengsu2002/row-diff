import csv
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import row_diff.snapshot as snapshot
from row_diff.snapshot import sorted_snapshot


class CompactionTests(unittest.TestCase):
    def test_logarithmic_run_metadata_and_exact_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.csv'
            with source.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['id', 'value'])
                writer.writerows((str(i), str(i * 7)) for i in reversed(range(513)))
            peaks = []
            original = snapshot._RunStore.write
            def observe(store, records):
                original(store, records)
                peaks.append(len(store.paths()))
            with patch.object(snapshot._RunStore, 'write', observe):
                with sorted_snapshot(source, ('id',), run_rows=1, fan_in=3,
                                     temp_dir=root) as (_, rows):
                    actual = list(rows)
            self.assertEqual(actual, [((str(i),), [str(i), str(i * 7)])
                                      for i in sorted(range(513), key=str)])
            self.assertLessEqual(max(peaks), 2 * (math.floor(math.log(513, 3)) + 1))
            self.assertEqual(list(root.iterdir()), [source])

    def test_compaction_failure_removes_all_scratch_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source.csv'
            source.write_text('id\na\nb\nc\nd\n')
            original = snapshot._merge
            def fail(paths):
                yield next(original(paths))
                raise OSError('simulated storage failure')
            with patch('row_diff.snapshot._merge', fail):
                with self.assertRaises(OSError):
                    with sorted_snapshot(source, ('id',), run_rows=1, fan_in=2,
                                         temp_dir=root) as (_, rows):
                        list(rows)
            self.assertEqual(list(root.iterdir()), [source])

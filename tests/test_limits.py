import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import row_diff.snapshot as snapshot
from row_diff.report import write_report
from row_diff.snapshot import SnapshotError, sorted_snapshot


class LimitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'data.csv'

    def read(self, **options):
        with sorted_snapshot(self.source, ('id',), temp_dir=self.root, **options) as (_, rows):
            return list(rows)

    def test_multiline_record_boundary(self):
        self.source.write_text('id,v\na,"b\nc"\n')
        self.assertEqual(self.read(max_record_chars=8)[0][1], ['a', 'b\nc'])
        with self.assertRaisesRegex(SnapshotError, 'character limit'):
            self.read(max_record_chars=7)
        self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_long_line_and_header(self):
        for content in ('id,' + 'x' * 40 + '\n', 'id,v\na,' + 'x' * 40 + '\n'):
            self.source.write_text(content)
            with self.assertRaises(SnapshotError):
                self.read(max_record_chars=10)
            self.assertEqual(list(self.root.iterdir()), [self.source])

    def test_utf8_budget_splits_runs(self):
        self.source.write_text('id,v\nc,雪雪\nb,雪雪\na,雪雪\n')
        sizes = []
        original = snapshot._RunStore.write
        def capture(store, records):
            records = list(records)
            sizes.append(len(records))
            return original(store, records)
        with patch.object(snapshot._RunStore, 'write', capture):
            rows = self.read(run_bytes=30, fan_in=2)
        self.assertEqual([r[0] for r in rows], [('a',), ('b',), ('c',)])
        self.assertEqual(sizes[:3], [1, 1, 1])

    def test_large_single_record(self):
        self.source.write_text('id,v\na,' + 'x' * 50 + '\n')
        self.assertEqual(len(self.read(run_bytes=1)[0][1][1]), 50)

    def test_invalid_limits(self):
        self.source.write_text('id\na\n')
        for name in ('run_bytes', 'max_record_chars'):
            for value in (0, -1, True, 1.5):
                with self.assertRaises(SnapshotError):
                    self.read(**{name: value})

    def test_limit_failure_preserves_report(self):
        self.source.write_text('id,v\na,"b\nc"\n')
        out = self.root / 'report'
        out.write_text('old report')
        with self.assertRaises(SnapshotError):
            write_report(self.source, self.source, ('id',), out,
                         max_record_chars=7, temp_dir=self.root)
        self.assertEqual(out.read_text(), 'old report')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['data.csv', 'report'])

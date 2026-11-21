import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import row_diff.snapshot as snapshot
from row_diff import SnapshotError, write_report
from row_diff.snapshot import sorted_snapshot
from row_diff.report import compare_snapshots


class InputChangeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old, self.new, self.out = [self.root / n for n in ('old.csv', 'new.csv', 'report')]
        self.old.write_text('id,v\na,old\n')
        self.new.write_text('id,v\na,new\n')
        self.out.write_text('previous')

    def test_mutation_after_sort_before_publication(self):
        @contextmanager
        def mutate(*args, **kwargs):
            with compare_snapshots(*args, **kwargs) as changes:
                yield changes
            self.old.write_text('id,v\na,altered\n')
        with patch('row_diff.report.compare_snapshots', mutate):
            with self.assertRaisesRegex(SnapshotError, 'changed'):
                write_report(self.old, self.new, ('id',), self.out, temp_dir=self.root)
        self.assertEqual(self.out.read_text(), 'previous')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['new.csv', 'old.csv', 'report'])

    def test_replacement_during_ingestion(self):
        original = snapshot._RunStore.write
        def replace(store, records):
            original(store, records)
            replacement = self.root / 'replacement'
            replacement.write_text(self.old.read_text())
            replacement.replace(self.old)
        with patch.object(snapshot._RunStore, 'write', replace):
            with self.assertRaisesRegex(SnapshotError, 'changed'):
                with sorted_snapshot(self.old, ('id',), run_rows=1, temp_dir=self.root):
                    pass
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ['new.csv', 'old.csv', 'report'])

    def test_directory_rejected(self):
        with self.assertRaisesRegex(SnapshotError, 'regular'):
            with sorted_snapshot(self.root, ('id',)):
                pass

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from row_diff.report import write_report
from row_diff.snapshot import SnapshotError


class ReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old, self.new, self.out = [self.root / n for n in ('old.csv', 'new.csv', 'report.jsonl')]
        self.write(self.old, [['id', 'v'], ['a', 'old'], ['b', 'gone']])
        self.write(self.new, [['v', 'id'], ['new\n雪', 'a'], ['added', 'c']])
        self.out.write_bytes(b'previous report\n')

    def write(self, path, rows):
        with path.open('w', encoding='utf-8', newline='') as handle:
            csv.writer(handle).writerows(rows)

    def publish(self, destination=None):
        return write_report(self.old, self.new, ('id',), destination or self.out,
                            run_rows=1, fan_in=2, temp_dir=self.root)

    def assert_preserved(self):
        self.assertEqual(self.out.read_bytes(), b'previous report\n')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['new.csv', 'old.csv', 'report.jsonl'])

    def test_complete_report_and_counts(self):
        self.assertEqual(self.publish(), {'added': 1, 'removed': 1, 'changed': 1})
        rows = [json.loads(line) for line in self.out.read_text().splitlines()]
        self.assertEqual([r['kind'] for r in rows], ['changed', 'removed', 'added'])
        self.assertEqual(rows[0]['after'], {'id': 'a', 'v': 'new\n雪'})
        self.assertEqual(rows[0]['columns'], ['v'])

    def test_late_duplicate_preserves_output(self):
        self.write(self.new, [['id', 'v'], ['a', 'new'], ['z', '1'], ['z', '2']])
        with self.assertRaisesRegex(SnapshotError, 'duplicate'):
            self.publish()
        self.assert_preserved()

    def test_malformed_input_preserves_output(self):
        self.new.write_text('id,v\na,"unterminated')
        with self.assertRaises(csv.Error):
            self.publish()
        self.assert_preserved()

    def test_disk_failure_preserves_output(self):
        with patch('row_diff.report.os.fsync', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError):
                self.publish()
        self.assert_preserved()

    def test_replace_failure_cleans_staging(self):
        with patch('row_diff.report.os.replace', side_effect=PermissionError('denied')):
            with self.assertRaises(PermissionError):
                self.publish()
        self.assert_preserved()

    def test_input_aliases_rejected(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.old)
        for destination in (self.old, alias):
            with self.assertRaises(ValueError):
                self.publish(destination)
        alias.unlink()
        alias.hardlink_to(self.old)
        with self.assertRaises(ValueError):
            self.publish(alias)
        self.assertEqual(self.old.read_text(), 'id,v\na,old\nb,gone\n')

    def test_no_changes_publishes_empty_report(self):
        self.new.write_bytes(self.old.read_bytes())
        self.assertEqual(self.publish(), {'added': 0, 'removed': 0, 'changed': 0})
        self.assertEqual(self.out.read_bytes(), b'')

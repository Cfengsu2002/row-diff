import csv
import random
import tempfile
import unittest
from pathlib import Path
from row_diff.snapshot import SnapshotError, sorted_snapshot


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'input.csv'
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()

    def write(self, rows):
        with self.source.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(rows)

    def read(self, keys=('id',), **options):
        with sorted_snapshot(self.source, keys, temp_dir=self.scratch, **options) as (header, records):
            return header, list(records)

    def test_multilevel_merge(self):
        rows = [[str(i), f'value,{i}\nline'] for i in range(217)]
        random.Random(42).shuffle(rows)
        self.write([['id', 'v'], *rows])
        header, records = self.read(run_rows=3, fan_in=2)
        self.assertEqual(header, ('id', 'v'))
        self.assertEqual([r for _, r in records], sorted(rows, key=lambda r: r[0]))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_duplicate_across_runs(self):
        self.write([['id'], ['a'], ['z'], ['a']])
        with self.assertRaisesRegex(SnapshotError, 'duplicate'):
            self.read(run_rows=1, fan_in=2)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_composite_keys(self):
        self.write([['group', 'id'], ['β', '2'], ['a', '10'], ['a', '02']])
        _, records = self.read(keys=('group', 'id'), run_rows=1)
        self.assertEqual([k for k, _ in records], [('a', '02'), ('a', '10'), ('β', '2')])

    def test_invalid_schema_rows(self):
        for rows in ([], [['id', 'id']], [['', 'id']], [['other']], [['id', 'v'], ['1']], [['id'], ['']], [['id'], ['1', '2']]):
            with self.subTest(rows=rows):
                self.write(rows)
                with self.assertRaises(SnapshotError):
                    self.read(run_rows=1)
                self.assertEqual(list(self.scratch.iterdir()), [])

    def test_empty_and_early_stop(self):
        self.write([['id']])
        self.assertEqual(self.read(), (('id',), []))
        self.write([['id'], ['b'], ['a']])
        with sorted_snapshot(self.source, ('id',), run_rows=1, temp_dir=self.scratch) as (_, records):
            self.assertEqual(next(records)[0], ('a',))
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_options(self):
        self.write([['id']])
        for options in ({'run_rows': 0}, {'fan_in': 1}, {'run_rows': True}):
            with self.assertRaises(SnapshotError):
                self.read(**options)
        for keys in ((), ('id', 'id')):
            with self.assertRaises(SnapshotError):
                self.read(keys=keys)

    def test_bom_and_broken_csv(self):
        self.source.write_text('\ufeffid,v\n1,ok\n', encoding='utf-8')
        self.assertEqual(self.read()[1], [(('1',), ['1', 'ok'])])
        self.source.write_text('id,v\n1,"unterminated', encoding='utf-8')
        with self.assertRaises(csv.Error):
            self.read()
        self.assertEqual(list(self.scratch.iterdir()), [])

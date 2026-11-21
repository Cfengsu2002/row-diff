import csv
import random
import tempfile
import unittest
from pathlib import Path

from row_diff.compare import compare_snapshots
from row_diff.snapshot import SnapshotError


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.scratch = self.root / 'scratch'
        self.scratch.mkdir()
        self.old = self.root / 'old.csv'
        self.new = self.root / 'new.csv'

    def write(self, path, rows):
        with path.open('w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerows(rows)

    def run_diff(self, keys=('id',)):
        with compare_snapshots(self.old, self.new, keys, run_rows=2, fan_in=2,
                               temp_dir=self.scratch) as changes:
            return list(changes)

    def test_add_remove_change_and_column_reorder(self):
        self.write(self.old, [['id', 'v'], ['3', 'gone'], ['1', 'same'], ['2', 'old']])
        self.write(self.new, [['v', 'id'], ['added', '4'], ['new', '2'], ['same', '1']])
        changes = self.run_diff()
        self.assertEqual([(c.kind, c.key) for c in changes],
                         [('changed', ('2',)), ('removed', ('3',)), ('added', ('4',))])
        self.assertEqual(changes[0].columns, ('v',))
        self.assertEqual(changes[0].before, {'id': '2', 'v': 'old'})
        self.assertEqual(changes[0].after, {'id': '2', 'v': 'new'})

    def test_random_reference_with_many_runs(self):
        rng = random.Random(17)
        old = {str(i): str(rng.randrange(10)) for i in rng.sample(range(300), 180)}
        new = {str(i): str(rng.randrange(10)) for i in rng.sample(range(300), 190)}
        old_rows, new_rows = list(old.items()), list(new.items())
        rng.shuffle(old_rows)
        rng.shuffle(new_rows)
        self.write(self.old, [['id', 'v'], *old_rows])
        self.write(self.new, [['id', 'v'], *new_rows])
        expected = [(('added' if k not in old else 'removed' if k not in new else 'changed'), (k,))
                    for k in sorted(old.keys() | new.keys())
                    if k not in old or k not in new or old[k] != new[k]]
        self.assertEqual([(c.kind, c.key) for c in self.run_diff()], expected)
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_unchanged_with_reordered_columns(self):
        self.write(self.old, [['id', 'v'], ['01', ' a\nb']])
        self.write(self.new, [['v', 'id'], [' a\nb', '01']])
        self.assertEqual(self.run_diff(), [])

    def test_empty_sides(self):
        for old, new, expected in (([], [], []), ([['a', '1']], [], ['removed']),
                                   ([], [['a', '1']], ['added'])):
            self.write(self.old, [['id', 'v'], *old])
            self.write(self.new, [['id', 'v'], *new])
            self.assertEqual([c.kind for c in self.run_diff()], expected)

    def test_schema_mismatch(self):
        self.write(self.old, [['id', 'v']])
        self.write(self.new, [['id', 'other']])
        with self.assertRaisesRegex(SnapshotError, 'column sets'):
            self.run_diff()
        self.assertEqual(list(self.scratch.iterdir()), [])

    def test_duplicate_detected_even_in_unchanged_tail(self):
        for duplicate_side in (self.old, self.new):
            self.write(self.old, [['id', 'v'], ['a', '1'], ['z', '2']])
            self.write(self.new, [['id', 'v'], ['a', '1'], ['z', '2']])
            self.write(duplicate_side, [['id', 'v'], ['a', '1'], ['z', '2'], ['z', '2']])
            with self.assertRaisesRegex(SnapshotError, 'duplicate'):
                self.run_diff()
            self.assertEqual(list(self.scratch.iterdir()), [])

    def test_early_close_cleanup(self):
        self.write(self.old, [['id'], ['a'], ['b']])
        self.write(self.new, [['id']])
        with compare_snapshots(self.old, self.new, ('id',), run_rows=1,
                               temp_dir=self.scratch) as changes:
            self.assertEqual(next(changes).kind, 'removed')
        self.assertEqual(list(self.scratch.iterdir()), [])

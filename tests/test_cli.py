import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.old, self.new, self.out = [self.root / n for n in ('old.csv', 'new.csv', 'out.jsonl')]
        self.old.write_text('region,id,v\nUS,a,old\n')
        self.new.write_text('id,v,region\na,new,US\nb,added,US\n')
        self.out.write_text('previous')

    def run_cli(self, *options):
        return subprocess.run([sys.executable, '-m', 'row_diff', str(self.old), str(self.new),
                               '--key', 'region', '--key', 'id', '--output', str(self.out),
                               '--run-rows', '1', '--fan-in', '2', *options],
                              capture_output=True, text=True, timeout=10, cwd=self.root,
                              env={**os.environ, 'PYTHONPATH': str(PROJECT)})

    def test_success_from_unrelated_working_directory(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'added': 1, 'removed': 0, 'changed': 1})
        self.assertEqual(result.stderr, '')
        rows = [json.loads(line) for line in self.out.read_text().splitlines()]
        self.assertEqual(rows[0]['key'], ['US', 'a'])
        self.assertEqual(rows[0]['after']['v'], 'new')

    def test_duplicate_error_does_not_echo_private_values(self):
        self.new.write_text('region,id,v\nUS,PRIVATE-KEY,SECRET\nUS,PRIVATE-KEY,SECRET2\n')
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, '')
        self.assertNotIn('PRIVATE', result.stderr)
        self.assertNotIn('SECRET', result.stderr)
        self.assertNotIn(str(self.root), result.stderr)
        self.assertEqual(self.out.read_text(), 'previous')

    def test_missing_input_and_invalid_encoding(self):
        self.new.unlink()
        self.assertEqual(self.run_cli().returncode, 3)
        self.new.write_bytes(b'id,v\n\xff,secret\n')
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('secret', result.stderr)
        self.assertEqual(self.out.read_text(), 'previous')

    def test_bad_options_preserve_output(self):
        for options in (('--fan-in', '1'), ('--run-rows', '0'),
                        ('--run-bytes', '-1'), ('--key', 'missing'),
                        ('--output', str(self.old))):
            result = self.run_cli(*options)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(self.out.read_text(), 'previous')
        self.assertEqual(self.old.read_text(), 'region,id,v\nUS,a,old\n')

    def test_oversized_record_preserves_output(self):
        result = self.run_cli('--max-record-chars', '5')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.out.read_text(), 'previous')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['new.csv', 'old.csv', 'out.jsonl'])

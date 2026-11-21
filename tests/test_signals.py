import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from row_diff.cli import main


PROJECT = Path(__file__).resolve().parents[1]
CHILD = '''
import sys
import signal
from contextlib import contextmanager
from unittest.mock import patch
from row_diff.cli import main
from row_diff.compare import Change

@contextmanager
def blocked(*args, **kwargs):
    def changes():
        yield Change('added', ('a',), None, {'id': 'a'}, ())
        print('READY', flush=True)
        signal.pause()
    yield changes()

with patch('row_diff.report.compare_snapshots', blocked):
    sys.exit(main(['old.csv', 'new.csv', '--key', 'id', '--output', 'out.jsonl']))
'''


@unittest.skipIf(os.name == 'nt', 'requires POSIX signals')
class SignalTests(unittest.TestCase):
    def test_signals_preserve_report_and_clean_stage(self):
        for sig, code in ((signal.SIGTERM, 143), (signal.SIGINT, 130)):
            with self.subTest(signal=sig), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'old.csv').write_text('id\n')
                (root / 'new.csv').write_text('id\na\n')
                (root / 'out.jsonl').write_text('previous')
                proc = subprocess.Popen([sys.executable, '-u', '-c', CHILD], cwd=root,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        text=True, env={**os.environ, 'PYTHONPATH': str(PROJECT)})
                try:
                    # 首条记录写出后再发送信号，避免启动时序竞争。
                    self.assertEqual(proc.stdout.readline().strip(), 'READY')
                    proc.send_signal(sig)
                    stdout, stderr = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, code, stderr)
                    self.assertEqual(stdout, '')
                    self.assertNotIn('Traceback', stderr)
                    self.assertEqual((root / 'out.jsonl').read_text(), 'previous')
                    self.assertEqual(sorted(p.name for p in root.iterdir()),
                                     ['new.csv', 'old.csv', 'out.jsonl'])
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.communicate()

    def test_handler_restored_after_failure_and_success(self):
        previous = signal.getsignal(signal.SIGTERM)
        for failure in (False, True):
            with patch('row_diff.cli._main', side_effect=ValueError('example') if failure else None,
                       return_value=0):
                if failure:
                    with self.assertRaises(ValueError):
                        main([])
                else:
                    self.assertEqual(main([]), 0)
            self.assertIs(signal.getsignal(signal.SIGTERM), previous)

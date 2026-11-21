"""Exercise the installed command outside the source checkout."""
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    examples = Path(__file__).resolve().parent
    command = shutil.which('row-diff')
    if command is None:
        raise RuntimeError('install row-diff before running this check')
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        for name in ('before.csv', 'after.csv'):
            shutil.copyfile(examples / name, root / name)
        result = subprocess.run([command, 'before.csv', 'after.csv', '--key', 'region',
                                 '--key', 'id', '--output', 'changes.jsonl', '--run-rows', '1',
                                 '--fan-in', '2'], cwd=root, env=env, capture_output=True,
                                text=True, check=True, timeout=20)
        assert json.loads(result.stdout) == {'added': 1, 'changed': 1, 'removed': 1}
        rows = [json.loads(line) for line in (root / 'changes.jsonl').read_text().splitlines()]
        assert [(row['kind'], row['key']) for row in rows] == [
            ('removed', ['EU', 'b']), ('changed', ['US', 'a']), ('added', ['US', 'c'])]
        assert rows[1]['after']['balance'] == '11'
        assert rows[1]['columns'] == ['balance']
        print('Installed command and complete report verified.')


if __name__ == '__main__':
    main()

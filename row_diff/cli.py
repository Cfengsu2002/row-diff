"""Compare local CSV snapshots and publish a validated change report."""
import argparse
import csv
import json
import signal
import threading
import sys

from .report import write_report
from .snapshot import SnapshotError


def positive_int(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError('must be a positive integer')
    return number


def _main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before')
    parser.add_argument('after')
    parser.add_argument('--key', action='append', required=True,
                        help='key column; repeat for composite keys in order')
    parser.add_argument('--output', required=True, help='JSON Lines report destination')
    parser.add_argument('--temp-dir')
    parser.add_argument('--run-rows', type=positive_int, default=10000)
    parser.add_argument('--run-bytes', type=positive_int, default=8 * 1024 * 1024)
    parser.add_argument('--max-record-chars', type=positive_int, default=1024 * 1024)
    parser.add_argument('--fan-in', type=positive_int, default=32)
    args = parser.parse_args(argv)
    if args.fan_in < 2:
        parser.error('--fan-in must be at least two')
    try:
        counts = write_report(args.before, args.after, args.key, args.output,
                              temp_dir=args.temp_dir, run_rows=args.run_rows,
                              run_bytes=args.run_bytes, fan_in=args.fan_in,
                              max_record_chars=args.max_record_chars)
    except (SnapshotError, csv.Error, UnicodeError, ValueError):
        print('Comparison failed: invalid snapshot or comparison settings; report not published.',
              file=sys.stderr)
        return 2
    except OSError:
        print('Comparison failed: file access or storage error; report not published.',
              file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print('Comparison interrupted; report publication may not have completed.', file=sys.stderr)
        return 130
    print(json.dumps(counts, sort_keys=True))
    return 0


class _TerminationRequested(BaseException):
    pass


def _terminate(signum, frame):
    raise _TerminationRequested


def main(argv=None):
    """Run CLI with SIGTERM cleanup on the main thread.

    Embedded callers on other threads keep existing signal behavior. SIGKILL
    cannot run cleanup. A signal concurrent with atomic replacement may leave
    the new complete report in place.
    """
    manages_signal = threading.current_thread() is threading.main_thread()
    previous = None
    if manages_signal:
        previous = signal.signal(signal.SIGTERM, _terminate)
    try:
        return _main(argv)
    except _TerminationRequested:
        print('Comparison terminated; report publication may not have completed.', file=sys.stderr)
        return 143
    finally:
        if manages_signal:
            signal.signal(signal.SIGTERM, previous)


if __name__ == '__main__':
    sys.exit(main())

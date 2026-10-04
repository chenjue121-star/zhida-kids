"""Run synthetic Phase D release evidence without loading real service secrets."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.v2.release.rehearsal import run_rehearsal


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True, help='Explicitly synthetic legacy JSON export')
    parser.add_argument('--output', type=Path, required=True, help='New isolated output directory; existing output is refused')
    args = parser.parse_args(argv)
    try:
        report = run_rehearsal(args.source, args.output)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

#!/usr/bin/env python3
"""Reproduce the anonymous pilot tables from package-local inputs; no model calls."""

import argparse
import json
from pathlib import Path
import sys

# Isolated Python (-I -S) omits the script directory from the import path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analysis_core import check_expected, compute, load_inputs
from outputs import build_tables, dump_json, write_figure, write_report, write_tables


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    package_analysis = Path(__file__).resolve().parent.parent
    parser.add_argument('--output-dir', type=Path, default=package_analysis/'generated',
                        help='Directory for new generated files (default: analysis/generated)')
    parser.add_argument('--skip-expected', action='store_true',
                        help='Do not read optional analysis/data/expected.json')
    parser.add_argument('--expected', type=Path,
                        help='Optional expected JSON within this package (relative names resolve from analysis/data)')
    args = parser.parse_args(argv)
    data_dir = package_analysis/'data'
    try:
        original, pairs, recommendations, corrections, human, register, concerns, hashes = load_inputs(data_dir)
        result, corrected = compute(original, pairs, recommendations, corrections, human, register, concerns)
        result['input_hashes'] = hashes
        expected_file = args.expected if args.expected is not None else data_dir/'expected.json'
        if args.expected is not None and not expected_file.is_absolute():
            expected_file = data_dir/expected_file
        expected_file = expected_file.resolve()
        if not expected_file.is_relative_to(package_analysis.resolve()):
            raise ValueError('Expected assertions must be inside this package analysis directory')
        if args.expected is not None and not expected_file.is_file():
            raise ValueError('Explicit expected assertion file does not exist')
        expected_checks = []
        if expected_file.is_file() and not args.skip_expected:
            expected = json.loads(expected_file.read_text(encoding='utf-8'))
            expected_checks = check_expected(result, expected)
        output_dir = args.output_dir.resolve()
        if output_dir == data_dir.resolve() or data_dir.resolve() in output_dir.parents:
            raise ValueError('Output directory must not overwrite package inputs')
        output_dir.mkdir(parents=True, exist_ok=True)
        dump_json(output_dir/'results.json', result)
        dump_json(output_dir/'scalar_claims.json', result['scalar_claims'])
        dump_json(output_dir/'input_hashes.json', hashes)
        dump_json(output_dir/'expected_checks.json', expected_checks)
        write_tables(build_tables(result, human, register, concerns), output_dir)
        write_figure(result, register, concerns, output_dir)
        write_report(result, hashes, expected_checks, output_dir)
        failed = [check for check in expected_checks if not check['pass']]
        print(json.dumps({'status': 'failed expected checks' if failed else 'ok',
                          'reviews': sum(result['scalar_claims']['reviews_by_purpose'].values()),
                          'corrections': len(result['applied_corrections']),
                          'expected_checks': len(expected_checks), 'failed_checks': len(failed)}))
        return 1 if failed else 0
    except (ValueError, KeyError, OSError, json.JSONDecodeError) as error:
        print(f'Reproduction failed: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())

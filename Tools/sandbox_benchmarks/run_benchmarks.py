#!/usr/bin/env python3
"""Runner: executes sandbox benchmarks across configurations, saves JSON results.

Usage:
    run_benchmarks.py --python PATH --profile NAME [--benchmark NAME]
                      [--output-dir DIR] [--label LABEL] [--scoped]
                      [-- PYPERF_ARGS...]

Examples:
    # Standard CPython baseline
    ./run_benchmarks.py --python /path/to/standard/python3 --profile disabled --label standard

    # Sandbox binary, sandbox disabled
    ./run_benchmarks.py --python /path/to/sandbox/python3 --profile disabled --label sandbox-disabled

    # Sandbox enabled with full lockdown
    ./run_benchmarks.py --python /path/to/sandbox/python3 --profile full_lockdown --label sandbox-full --scoped
"""

import argparse
import json
import os
import subprocess
import sys
import time

BENCHMARKS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'benchmarks')
DEFAULT_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results')

# All benchmark scripts
ALL_BENCHMARKS = [
    'bench_int_arithmetic',
    'bench_str_ops',
    'bench_bytes_ops',
    'bench_list_ops',
    'bench_dict_ops',
    'bench_set_ops',
    'bench_tuple_ops',
    'bench_float_ops',
    'bench_iteration',
    'bench_function_calls',
    'bench_attribute_access',
    'bench_class_creation',
    'bench_general_compute',
    'bench_opcount_overhead',
]

# Benchmark/profile incompatibilities — skip these combinations
SKIP_COMBINATIONS = {
    # float bench doesn't work if allow_float=False
    # (currently all profiles allow float, but this is here for future-proofing)
}


def discover_benchmarks():
    """Discover available benchmark scripts."""
    benchmarks = []
    for fname in sorted(os.listdir(BENCHMARKS_DIR)):
        if fname.startswith('bench_') and fname.endswith('.py'):
            name = fname[:-3]  # strip .py
            benchmarks.append(name)
    return benchmarks


def should_skip(benchmark, profile):
    """Check if a benchmark/profile combination should be skipped."""
    return (benchmark, profile) in SKIP_COMBINATIONS


def run_benchmark(python_path, benchmark, profile, scoped, output_dir, pyperf_args):
    """Run a single benchmark script as a subprocess.

    Returns (success, output_file) tuple.
    """
    script_path = os.path.join(BENCHMARKS_DIR, f'{benchmark}.py')
    output_file = os.path.join(output_dir, f'{benchmark}.json')

    cmd = [
        python_path,
        script_path,
        '--sandbox-profile', profile,
        '--output', output_file,
    ]

    if scoped:
        cmd.append('--scoped')

    # Forward extra pyperf args
    if pyperf_args:
        cmd.extend(pyperf_args)

    env = os.environ.copy()
    env['PYTHONHASHSEED'] = '0'
    # Add the sandbox_benchmarks dir to PYTHONPATH so imports work
    bench_parent = os.path.dirname(os.path.abspath(__file__))
    if 'PYTHONPATH' in env:
        env['PYTHONPATH'] = bench_parent + os.pathsep + env['PYTHONPATH']
    else:
        env['PYTHONPATH'] = bench_parent

    print(f"  Running {benchmark}...", flush=True)
    start = time.time()

    try:
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per benchmark
        )
        elapsed = time.time() - start

        if result.returncode != 0:
            print(f"    FAILED ({elapsed:.1f}s)")
            print(f"    stderr: {result.stderr[:500]}")
            return False, output_file

        print(f"    OK ({elapsed:.1f}s)")
        return True, output_file

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"    TIMEOUT ({elapsed:.1f}s)")
        return False, output_file
    except Exception as e:
        print(f"    ERROR: {e}")
        return False, output_file


def main():
    parser = argparse.ArgumentParser(
        description='Run sandbox benchmark suite')
    parser.add_argument('--python', default=None,
                        help='Path to Python binary to benchmark')
    parser.add_argument('--profile', default=None,
                        help='Sandbox restriction profile name')
    parser.add_argument('--benchmark', action='append', default=None,
                        help='Specific benchmark(s) to run (can repeat; default: all)')
    parser.add_argument('--output-dir', default=None,
                        help='Output directory for results (default: results/<label>)')
    parser.add_argument('--label', default=None,
                        help='Label for this run (default: profile name)')
    parser.add_argument('--scoped', action='store_true', default=False,
                        help='Enable sandbox scope tracking')
    parser.add_argument('--list', action='store_true',
                        help='List available benchmarks and exit')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be run without executing')

    # Parse known args, treat rest as pyperf passthrough
    args, pyperf_args = parser.parse_known_args()

    # Strip leading '--' separator if present
    if pyperf_args and pyperf_args[0] == '--':
        pyperf_args = pyperf_args[1:]

    if args.list:
        print("Available benchmarks:")
        for name in discover_benchmarks():
            print(f"  {name}")
        return 0

    # Validate required args
    if not args.python:
        parser.error("--python is required")
    if not args.profile:
        parser.error("--profile is required")

    # Determine which benchmarks to run
    if args.benchmark:
        benchmarks = args.benchmark
    else:
        benchmarks = ALL_BENCHMARKS

    # Determine output directory
    label = args.label or args.profile
    output_dir = args.output_dir or os.path.join(DEFAULT_OUTPUT_DIR, label)
    os.makedirs(output_dir, exist_ok=True)

    # Verify Python binary exists
    if not os.path.isfile(args.python):
        print(f"Error: Python binary not found: {args.python}", file=sys.stderr)
        return 1

    print(f"Sandbox Benchmark Runner")
    print(f"  Python:  {args.python}")
    print(f"  Profile: {args.profile}")
    print(f"  Scoped:  {args.scoped}")
    print(f"  Label:   {label}")
    print(f"  Output:  {output_dir}")
    print(f"  Benchmarks: {len(benchmarks)}")
    if pyperf_args:
        print(f"  pyperf args: {' '.join(pyperf_args)}")
    print()

    if args.dry_run:
        print("Dry run — would execute:")
        for bench in benchmarks:
            if should_skip(bench, args.profile):
                print(f"  SKIP {bench} (incompatible with {args.profile})")
            else:
                print(f"  RUN  {bench}")
        return 0

    # Run benchmarks
    results = {}
    total = 0
    passed = 0
    skipped = 0
    failed = 0

    start_time = time.time()

    for bench in benchmarks:
        total += 1

        if should_skip(bench, args.profile):
            print(f"  Skipping {bench} (incompatible with {args.profile})")
            skipped += 1
            continue

        success, output_file = run_benchmark(
            args.python, bench, args.profile, args.scoped,
            output_dir, pyperf_args)

        results[bench] = {
            'success': success,
            'output_file': output_file,
        }

        if success:
            passed += 1
        else:
            failed += 1

    elapsed = time.time() - start_time

    # Write summary
    summary = {
        'label': label,
        'profile': args.profile,
        'python': args.python,
        'scoped': args.scoped,
        'total': total,
        'passed': passed,
        'failed': failed,
        'skipped': skipped,
        'elapsed_seconds': elapsed,
        'benchmarks': results,
    }
    summary_file = os.path.join(output_dir, '_summary.json')
    with open(summary_file, 'w') as f:
        json.dump(summary, f, indent=2)

    print()
    print(f"Done in {elapsed:.1f}s: {passed} passed, {failed} failed, {skipped} skipped")
    print(f"Results saved to: {output_dir}")
    print(f"Summary: {summary_file}")

    return 1 if failed > 0 else 0


if __name__ == '__main__':
    sys.exit(main())

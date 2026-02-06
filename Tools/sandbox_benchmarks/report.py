#!/usr/bin/env python3
"""Report: combines benchmark results into a comparison report.

Usage:
    report.py --baseline-dir DIR --compare-dir DIR [DIR ...]
              [--output FILE] [--format markdown|csv]

Examples:
    # Compare sandbox-disabled vs standard baseline
    ./report.py --baseline-dir results/standard --compare-dir results/sandbox-disabled

    # Full comparison across all profiles
    ./report.py --baseline-dir results/standard \\
                --compare-dir results/sandbox-disabled results/sandbox-nolimits \\
                              results/sandbox-size-limits results/sandbox-full \\
                --output report.md
"""

import argparse
import json
import os
import sys
import platform
from datetime import datetime

try:
    import pyperf
except ImportError:
    pyperf = None


# Benchmark categories for the summary table
CATEGORIES = {
    'Int Arithmetic': ['bench_int_arithmetic'],
    'String Ops': ['bench_str_ops'],
    'Bytes Ops': ['bench_bytes_ops'],
    'List Ops': ['bench_list_ops'],
    'Dict Ops': ['bench_dict_ops'],
    'Set Ops': ['bench_set_ops'],
    'Tuple Ops': ['bench_tuple_ops'],
    'Float Ops': ['bench_float_ops'],
    'Iteration': ['bench_iteration'],
    'Function Calls': ['bench_function_calls'],
    'Attribute Access': ['bench_attribute_access'],
    'Class Creation': ['bench_class_creation'],
    'General Compute': ['bench_general_compute'],
    'Opcode Counting': ['bench_opcount_overhead'],
}


def load_results_dir(results_dir):
    """Load all pyperf JSON results from a directory.

    Returns dict mapping benchmark_name -> pyperf.BenchmarkSuite or
    dict of raw benchmark data.
    """
    results = {}

    if not os.path.isdir(results_dir):
        print(f"Warning: results directory not found: {results_dir}",
              file=sys.stderr)
        return results

    for fname in sorted(os.listdir(results_dir)):
        if not fname.endswith('.json') or fname.startswith('_'):
            continue

        bench_name = fname[:-5]  # strip .json
        filepath = os.path.join(results_dir, fname)

        try:
            if pyperf is not None:
                suite = pyperf.BenchmarkSuite.load(filepath)
                results[bench_name] = suite
            else:
                with open(filepath) as f:
                    data = json.load(f)
                results[bench_name] = data
        except Exception as e:
            print(f"Warning: failed to load {filepath}: {e}",
                  file=sys.stderr)

    return results


def load_summary(results_dir):
    """Load the _summary.json if present."""
    summary_file = os.path.join(results_dir, '_summary.json')
    if os.path.isfile(summary_file):
        with open(summary_file) as f:
            return json.load(f)
    return None


def get_benchmark_means(suite):
    """Extract mean times from a pyperf BenchmarkSuite.

    Returns dict mapping sub-benchmark name -> mean time in seconds.
    """
    means = {}
    if pyperf is not None and isinstance(suite, pyperf.BenchmarkSuite):
        for bench in suite:
            means[bench.get_name()] = bench.mean()
    elif isinstance(suite, dict):
        # Raw JSON format
        benchmarks = suite.get('benchmarks', [])
        if not benchmarks and 'metadata' in suite:
            # Single benchmark file
            values = suite.get('values', [])
            if values:
                name = suite.get('metadata', {}).get('name', 'unknown')
                flat = []
                for run in values:
                    if isinstance(run, list):
                        flat.extend(run)
                    else:
                        flat.append(run)
                if flat:
                    means[name] = sum(flat) / len(flat)
        else:
            for b in benchmarks:
                name = b.get('metadata', {}).get('name', 'unknown')
                values = b.get('values', [])
                flat = []
                for run in values:
                    if isinstance(run, list):
                        flat.extend(run)
                    else:
                        flat.append(run)
                if flat:
                    means[name] = sum(flat) / len(flat)
    return means


def compute_overhead(baseline_mean, compare_mean):
    """Compute overhead percentage.

    Returns (overhead_pct, formatted_string).
    """
    if baseline_mean <= 0:
        return 0.0, "N/A"

    overhead = (compare_mean - baseline_mean) / baseline_mean * 100
    if abs(overhead) < 0.05:
        return overhead, "~0%"
    sign = "+" if overhead > 0 else ""
    return overhead, f"{sign}{overhead:.1f}%"


def format_time(seconds):
    """Format time value for display."""
    if seconds < 1e-6:
        return f"{seconds * 1e9:.1f} ns"
    elif seconds < 1e-3:
        return f"{seconds * 1e6:.1f} us"
    elif seconds < 1.0:
        return f"{seconds * 1e3:.2f} ms"
    else:
        return f"{seconds:.3f} s"


def generate_markdown_report(baseline_dir, compare_dirs, output_file=None):
    """Generate a markdown comparison report."""
    lines = []

    # Load all results
    baseline_label = os.path.basename(baseline_dir)
    baseline_results = load_results_dir(baseline_dir)
    baseline_summary = load_summary(baseline_dir)

    compare_data = []
    for cdir in compare_dirs:
        label = os.path.basename(cdir)
        results = load_results_dir(cdir)
        summary = load_summary(cdir)
        compare_data.append((label, results, summary))

    # Header
    lines.append("# Sandbox Benchmark Report")
    lines.append("")

    # Environment
    lines.append("## Environment")
    lines.append(f"- Platform: {platform.system()} {platform.machine()}")
    lines.append(f"- Python: {platform.python_version()}")
    lines.append(f"- CPU: {platform.processor() or 'unknown'}")
    lines.append(f"- Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"- Baseline: `{baseline_label}`")
    compare_labels = [c[0] for c in compare_data]
    lines.append(f"- Compared: {', '.join(f'`{l}`' for l in compare_labels)}")
    lines.append("")

    # Summary table
    lines.append("## Summary (mean overhead vs baseline)")
    lines.append("")

    # Build header row
    header = ["Category", "Baseline"]
    for label, _, _ in compare_data:
        header.append(label)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join(["---"] * len(header)) + "|")

    # Compute category-level overheads
    for category, bench_names in CATEGORIES.items():
        row = [category]

        # Collect all sub-benchmark means for baseline
        baseline_cat_means = {}
        for bench_name in bench_names:
            if bench_name in baseline_results:
                means = get_benchmark_means(baseline_results[bench_name])
                baseline_cat_means.update(means)

        if not baseline_cat_means:
            row.append("N/A")
            for _ in compare_data:
                row.append("N/A")
            lines.append("| " + " | ".join(row) + " |")
            continue

        # Average baseline time
        avg_baseline = sum(baseline_cat_means.values()) / len(baseline_cat_means)
        row.append(format_time(avg_baseline))

        # Compare each profile
        for label, results, _ in compare_data:
            compare_cat_means = {}
            for bench_name in bench_names:
                if bench_name in results:
                    means = get_benchmark_means(results[bench_name])
                    compare_cat_means.update(means)

            if not compare_cat_means:
                row.append("N/A")
                continue

            # Match sub-benchmarks that exist in both
            overheads = []
            for sub_name, base_val in baseline_cat_means.items():
                if sub_name in compare_cat_means:
                    pct = (compare_cat_means[sub_name] - base_val) / base_val * 100
                    overheads.append(pct)

            if overheads:
                avg_overhead = sum(overheads) / len(overheads)
                sign = "+" if avg_overhead > 0 else ""
                row.append(f"{sign}{avg_overhead:.1f}%")
            else:
                row.append("N/A")

        lines.append("| " + " | ".join(row) + " |")

    lines.append("")

    # Detailed results per benchmark
    lines.append("## Detailed Results")
    lines.append("")

    all_bench_names = sorted(set(
        list(baseline_results.keys()) +
        [k for _, r, _ in compare_data for k in r.keys()]
    ))

    for bench_name in all_bench_names:
        lines.append(f"### {bench_name}")
        lines.append("")

        # Get all sub-benchmark names
        all_sub_names = set()
        baseline_means = {}
        if bench_name in baseline_results:
            baseline_means = get_benchmark_means(baseline_results[bench_name])
            all_sub_names.update(baseline_means.keys())

        compare_means_list = []
        for label, results, _ in compare_data:
            means = {}
            if bench_name in results:
                means = get_benchmark_means(results[bench_name])
                all_sub_names.update(means.keys())
            compare_means_list.append((label, means))

        if not all_sub_names:
            lines.append("No data available.")
            lines.append("")
            continue

        # Table header
        header = ["Benchmark", baseline_label]
        for label, _ in compare_means_list:
            header.append(label)
        lines.append("| " + " | ".join(header) + " |")
        lines.append("|" + "|".join(["---"] * len(header)) + "|")

        for sub_name in sorted(all_sub_names):
            row = [sub_name]

            # Baseline value
            base_val = baseline_means.get(sub_name)
            if base_val is not None:
                row.append(format_time(base_val))
            else:
                row.append("N/A")

            # Compare values with overhead
            for label, means in compare_means_list:
                comp_val = means.get(sub_name)
                if comp_val is not None and base_val is not None:
                    _, overhead_str = compute_overhead(base_val, comp_val)
                    row.append(f"{format_time(comp_val)} ({overhead_str})")
                elif comp_val is not None:
                    row.append(format_time(comp_val))
                else:
                    row.append("N/A")

            lines.append("| " + " | ".join(row) + " |")

        lines.append("")

    # Statistical notes
    lines.append("## Notes")
    lines.append("")
    lines.append("- Overhead percentages are computed as: "
                 "(compare_mean - baseline_mean) / baseline_mean * 100")
    lines.append("- Summary shows the average overhead across all "
                 "sub-benchmarks in each category")
    lines.append("- Times are mean values reported by pyperf")
    if pyperf is None:
        lines.append("- **pyperf not installed**: using raw JSON parsing "
                     "(install pyperf for statistical significance testing)")
    lines.append("")

    report = "\n".join(lines)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(report)
        print(f"Report written to: {output_file}")
    else:
        print(report)

    return report


def generate_csv_report(baseline_dir, compare_dirs, output_file=None):
    """Generate a CSV comparison report."""
    import csv
    import io

    baseline_label = os.path.basename(baseline_dir)
    baseline_results = load_results_dir(baseline_dir)

    compare_data = []
    for cdir in compare_dirs:
        label = os.path.basename(cdir)
        results = load_results_dir(cdir)
        compare_data.append((label, results))

    buf = io.StringIO()
    writer = csv.writer(buf)

    # Header
    header = ['benchmark', 'sub_benchmark', f'{baseline_label}_mean_s']
    for label, _ in compare_data:
        header.extend([f'{label}_mean_s', f'{label}_overhead_pct'])
    writer.writerow(header)

    # Data rows
    all_bench_names = sorted(set(
        list(baseline_results.keys()) +
        [k for _, r in compare_data for k in r.keys()]
    ))

    for bench_name in all_bench_names:
        baseline_means = {}
        if bench_name in baseline_results:
            baseline_means = get_benchmark_means(baseline_results[bench_name])

        compare_means_list = []
        for label, results in compare_data:
            means = {}
            if bench_name in results:
                means = get_benchmark_means(results[bench_name])
            compare_means_list.append((label, means))

        all_sub_names = set(baseline_means.keys())
        for _, means in compare_means_list:
            all_sub_names.update(means.keys())

        for sub_name in sorted(all_sub_names):
            row = [bench_name, sub_name]
            base_val = baseline_means.get(sub_name)
            row.append(f"{base_val:.9f}" if base_val is not None else "")

            for label, means in compare_means_list:
                comp_val = means.get(sub_name)
                if comp_val is not None:
                    row.append(f"{comp_val:.9f}")
                    if base_val is not None and base_val > 0:
                        pct = (comp_val - base_val) / base_val * 100
                        row.append(f"{pct:.2f}")
                    else:
                        row.append("")
                else:
                    row.extend(["", ""])

            writer.writerow(row)

    csv_content = buf.getvalue()

    if output_file:
        with open(output_file, 'w') as f:
            f.write(csv_content)
        print(f"CSV report written to: {output_file}")
    else:
        print(csv_content)

    return csv_content


def main():
    parser = argparse.ArgumentParser(
        description='Generate sandbox benchmark comparison report')
    parser.add_argument('--baseline-dir', required=True,
                        help='Directory with baseline pyperf results')
    parser.add_argument('--compare-dir', nargs='+', required=True,
                        help='Directory(ies) with comparison pyperf results')
    parser.add_argument('--output', default=None,
                        help='Output file (default: stdout)')
    parser.add_argument('--format', choices=['markdown', 'csv'],
                        default='markdown',
                        help='Output format (default: markdown)')

    args = parser.parse_args()

    if args.format == 'csv':
        generate_csv_report(args.baseline_dir, args.compare_dir, args.output)
    else:
        generate_markdown_report(args.baseline_dir, args.compare_dir, args.output)

    return 0


if __name__ == '__main__':
    sys.exit(main())

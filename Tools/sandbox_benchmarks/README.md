# Sandbox Benchmark Suite

Benchmark suite for measuring the performance overhead of CPython's sandbox enforcement layer. Compares standard CPython against sandboxed CPython with various restriction profiles using [pyperf](https://github.com/psf/pyperf) for statistically rigorous measurements.

## Quick Start

```bash
# 1. Install pyperf
./python -m pip install pyperf

# 2. Run all benchmarks with sandbox disabled (baseline)
./run_benchmarks.py --python ./python --profile disabled --label sandbox-disabled -- --fast

# 3. Run all benchmarks with full sandbox restrictions
./run_benchmarks.py --python ./python --profile full_lockdown --label sandbox-full --scoped -- --fast

# 4. Generate comparison report
./report.py --baseline-dir results/sandbox-disabled \
            --compare-dir results/sandbox-full \
            --output report.md
```

## Directory Structure

```
Tools/sandbox_benchmarks/
├── run_benchmarks.py          # Runner: executes benchmarks, saves JSON results
├── report.py                  # Report: combines results into markdown/CSV tables
├── profiles.py                # Restriction profile definitions
├── bench_utils.py             # Shared utilities (pyperf integration, sandbox setup)
├── build_binaries.sh          # Helper to build standard + sandbox binaries
├── requirements.txt           # pyperf dependency
├── README.md                  # This file
├── results/                   # Output directory for JSON results
└── benchmarks/                # Individual benchmark scripts
    ├── bench_int_arithmetic.py
    ├── bench_str_ops.py
    ├── bench_bytes_ops.py
    ├── bench_list_ops.py
    ├── bench_dict_ops.py
    ├── bench_set_ops.py
    ├── bench_tuple_ops.py
    ├── bench_float_ops.py
    ├── bench_iteration.py
    ├── bench_function_calls.py
    ├── bench_attribute_access.py
    ├── bench_class_creation.py
    ├── bench_general_compute.py
    └── bench_opcount_overhead.py
```

## Restriction Profiles

8 profiles defined in `profiles.py`, each enabling different sandbox features to isolate their overhead:

| Profile | Description | What It Measures |
|---------|-------------|------------------|
| `disabled` | Sandbox exists but not enabled | Compiled-in check site overhead (`_PySandbox_IsEnforced() -> return`) |
| `enabled_nolimits` | Enabled, all limits=0 (no limit) | Deeper branch chain in sandbox prologue |
| `size_limits_only` | Only size limits active | Full prologue + scope check + size comparisons |
| `iteration_limits` | Size limits + `max_iterations` | Iterator wrapping + per-yield counter |
| `dunder_blocked` | Size limits + `allow_dunder_access=False` | String check on attribute access |
| `frozen_mode` | Size limits + `frozen_mode=True` | Set lookup on every setattr |
| `opcode_restrict` | Size limits + `opcode_restrict_mode=True` | Bitmap check in DISPATCH |
| `full_lockdown` | All restrictions active | Everything combined |

Limits are set generously (e.g., `max_list_size=500000`) so benchmarks never hit them. We measure the overhead of **checking**, not **enforcing**.

## Benchmarks

### Micro-benchmarks

Each isolates a specific sandbox check point:

| Benchmark | Operations | Sandbox Check Exercised |
|-----------|-----------|------------------------|
| `bench_int_arithmetic` | add, mul, pow, divmod (small + medium ints) | `_PySandbox_CheckIntSize` |
| `bench_str_ops` | concat, join, split, format, replace, encode | `_PySandbox_CheckStrLength` |
| `bench_bytes_ops` | concat, join, split, from_list, decode | `_PySandbox_CheckBytesLength` |
| `bench_list_ops` | append, comprehension, extend, sort, copy, pop | `_PySandbox_CheckListSize` |
| `bench_dict_ops` | insert, comprehension, update, lookup, copy, delete | `_PySandbox_CheckDictSize` |
| `bench_set_ops` | add, union, intersection, difference, contains | `_PySandbox_CheckSetSize` |
| `bench_tuple_ops` | create, concat, unpack, slice, index | `_PySandbox_CheckTupleSize` |
| `bench_float_ops` | arithmetic, math.sqrt/sin/log, create, convert | `_PySandbox_CheckTypeAllowed` |
| `bench_iteration` | for/range, generators, comprehensions, zip, enumerate | `_PySandbox_WrapIterator` |
| `bench_function_calls` | empty, args, kwargs, builtins, methods, recursive | DISPATCH overhead |
| `bench_attribute_access` | getattr, setattr, dunder, property, slots | `CheckDunderAccess` / `CheckFrozen` |
| `bench_class_creation` | class def, inheritance, instantiation, methods | `_PySandbox_CheckMetaclassAllowed` |

### Macro-benchmarks

Realistic combined workloads:

| Benchmark | Workload |
|-----------|----------|
| `bench_general_compute` | fibonacci, nbody, spectral_norm, fannkuch, json encode/decode, regex, matrix multiply |

### Special

| Benchmark | Purpose |
|-----------|---------|
| `bench_opcount_overhead` | Compares code compiled with vs without `PyCF_SANDBOX_COUNT=0x8000` to measure the SANDBOX_COUNT opcode overhead |

## Running Individual Benchmarks

Each benchmark script can be run directly. They accept pyperf arguments plus `--sandbox-profile` and `--scoped`:

```bash
# Run a single benchmark with default (disabled) profile
PYTHONPATH=Tools/sandbox_benchmarks \
  ./python Tools/sandbox_benchmarks/benchmarks/bench_int_arithmetic.py

# Run with a specific sandbox profile and scope tracking
PYTHONPATH=Tools/sandbox_benchmarks \
  ./python Tools/sandbox_benchmarks/benchmarks/bench_int_arithmetic.py \
    --sandbox-profile size_limits_only --scoped

# Save results to JSON
PYTHONPATH=Tools/sandbox_benchmarks \
  ./python Tools/sandbox_benchmarks/benchmarks/bench_int_arithmetic.py \
    --sandbox-profile full_lockdown --scoped \
    --output results/int_arithmetic_full.json

# Use pyperf's --fast flag for quicker (less precise) results
PYTHONPATH=Tools/sandbox_benchmarks \
  ./python Tools/sandbox_benchmarks/benchmarks/bench_str_ops.py \
    --sandbox-profile disabled --fast

# Rigorous mode for production measurements
PYTHONPATH=Tools/sandbox_benchmarks \
  ./python Tools/sandbox_benchmarks/benchmarks/bench_iteration.py \
    --sandbox-profile iteration_limits --scoped --rigorous
```

### Benchmark-specific arguments

| Argument | Description |
|----------|-------------|
| `--sandbox-profile NAME` | Sandbox restriction profile (default: `disabled`) |
| `--scoped` | Register sandbox filename for scope tracking |
| `--output FILE` | Save pyperf JSON results to file |
| `--fast` | Quick mode (3 processes, 3 values) — good for development |
| `--rigorous` | Rigorous mode (25 processes, 100 values) — for production measurements |
| `--quiet` | Suppress pyperf warnings |
| `--loops N` | Override number of inner loops |
| `--min-time SEC` | Minimum time per calibration |

## Using the Runner

The runner (`run_benchmarks.py`) executes all (or selected) benchmarks as subprocesses:

```bash
# List available benchmarks
./run_benchmarks.py --list

# Run all benchmarks with a profile
./run_benchmarks.py --python ./python --profile disabled --label sandbox-disabled

# Run specific benchmarks
./run_benchmarks.py --python ./python --profile full_lockdown --label sandbox-full --scoped \
    --benchmark bench_int_arithmetic --benchmark bench_str_ops

# Pass extra pyperf args after --
./run_benchmarks.py --python ./python --profile disabled --label baseline \
    -- --fast --quiet

# Dry run (show what would execute)
./run_benchmarks.py --python ./python --profile disabled --label test --dry-run
```

### Runner arguments

| Argument | Description |
|----------|-------------|
| `--python PATH` | Path to Python binary to benchmark (required) |
| `--profile NAME` | Sandbox restriction profile name (required) |
| `--benchmark NAME` | Specific benchmark(s) to run (repeatable; default: all) |
| `--output-dir DIR` | Output directory (default: `results/<label>`) |
| `--label LABEL` | Label for this run (default: profile name) |
| `--scoped` | Enable sandbox scope tracking |
| `--list` | List available benchmarks and exit |
| `--dry-run` | Show what would be run without executing |
| `-- ARGS...` | Extra arguments forwarded to pyperf |

### Results

Results are saved as pyperf JSON files in `results/<label>/`:

```
results/
├── sandbox-disabled/
│   ├── _summary.json
│   ├── bench_int_arithmetic.json
│   ├── bench_str_ops.json
│   └── ...
├── sandbox-full/
│   ├── _summary.json
│   ├── bench_int_arithmetic.json
│   └── ...
```

## Generating Reports

The report tool (`report.py`) compares results across profiles:

```bash
# Markdown report (default)
./report.py --baseline-dir results/sandbox-disabled \
            --compare-dir results/sandbox-full

# Compare multiple profiles
./report.py --baseline-dir results/sandbox-disabled \
            --compare-dir results/sandbox-nolimits \
                          results/sandbox-size-limits \
                          results/sandbox-iteration \
                          results/sandbox-full \
            --output report.md

# CSV format
./report.py --baseline-dir results/sandbox-disabled \
            --compare-dir results/sandbox-full \
            --format csv --output report.csv
```

### Report arguments

| Argument | Description |
|----------|-------------|
| `--baseline-dir DIR` | Directory with baseline pyperf results (required) |
| `--compare-dir DIR [DIR ...]` | Comparison result directory(ies) (required) |
| `--output FILE` | Output file (default: stdout) |
| `--format markdown\|csv` | Output format (default: markdown) |

## Full Comparison Workflow

To run the complete comparison across all profiles:

```bash
cd Tools/sandbox_benchmarks

# 1. Baseline (sandbox disabled)
./run_benchmarks.py --python ../../python --profile disabled \
    --label sandbox-disabled -- --fast --quiet

# 2. Enabled, no limits
./run_benchmarks.py --python ../../python --profile enabled_nolimits \
    --label sandbox-nolimits --scoped -- --fast --quiet

# 3. Size limits only
./run_benchmarks.py --python ../../python --profile size_limits_only \
    --label sandbox-size-limits --scoped -- --fast --quiet

# 4. Iteration limits
./run_benchmarks.py --python ../../python --profile iteration_limits \
    --label sandbox-iteration --scoped -- --fast --quiet

# 5. Dunder blocked
./run_benchmarks.py --python ../../python --profile dunder_blocked \
    --label sandbox-dunder --scoped -- --fast --quiet

# 6. Frozen mode
./run_benchmarks.py --python ../../python --profile frozen_mode \
    --label sandbox-frozen --scoped -- --fast --quiet

# 7. Opcode restrict
./run_benchmarks.py --python ../../python --profile opcode_restrict \
    --label sandbox-opcodes --scoped -- --fast --quiet

# 8. Full lockdown
./run_benchmarks.py --python ../../python --profile full_lockdown \
    --label sandbox-full --scoped -- --fast --quiet

# 9. Generate report
./report.py --baseline-dir results/sandbox-disabled \
            --compare-dir results/sandbox-nolimits \
                          results/sandbox-size-limits \
                          results/sandbox-iteration \
                          results/sandbox-dunder \
                          results/sandbox-frozen \
                          results/sandbox-opcodes \
                          results/sandbox-full \
            --output BENCHMARK-REPORT.md
```

## Building Standard + Sandbox Binaries

For a true baseline comparison against standard CPython (without any sandbox code compiled in):

```bash
# Build both binaries with PGO
./build_binaries.sh --install-dir /tmp/sandbox-bench

# Quick build without PGO (faster, but less representative)
./build_binaries.sh --install-dir /tmp/sandbox-bench --no-pgo

# Then benchmark both
./run_benchmarks.py --python /tmp/sandbox-bench/standard/bin/python3 \
    --profile disabled --label standard -- --fast --quiet

./run_benchmarks.py --python /tmp/sandbox-bench/sandbox/bin/python3 \
    --profile disabled --label sandbox-disabled -- --fast --quiet

# Compare
./report.py --baseline-dir results/standard \
            --compare-dir results/sandbox-disabled
```

## Design Notes

- **pyperf for timing**: Provides statistical rigor (warmup calibration, outlier detection, significance testing)
- **Subprocess isolation**: Each benchmark runs as a separate process via pyperf's worker process model
- **Scope via compile()**: Workload code is compiled with `compile(source, "<sandbox_bench>", "exec")` and registered via `sys.sandbox.add_filename("<sandbox_bench>")` so sandbox scope checks fire
- **While-loops for timing**: Inner benchmark loops use `while` + counter (not `for i in range()`) to avoid iteration wrapper overhead polluting non-iteration benchmarks
- **Generous limits**: Limits set high enough that benchmarks never hit them — we measure the cost of **checking**, not **enforcing**

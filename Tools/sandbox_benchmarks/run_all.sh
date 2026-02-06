#!/bin/bash
# Run all sandbox benchmark profiles sequentially and generate report.
#
# Usage:
#   ./run_all.sh                     # default: use ./python, --fast mode
#   ./run_all.sh /path/to/python     # custom binary
#   ./run_all.sh ./python --rigorous # pass extra pyperf args
#
# Results are saved to results/<profile>/ and the final report to BENCHMARK-REPORT.md

set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${1:-../../python}"
shift 2>/dev/null || true
PYPERF_ARGS="${*:---fast}"

RUNNER="../../python run_benchmarks.py"
RESULTS="results"

echo "============================================"
echo " Sandbox Benchmark Suite"
echo "============================================"
echo "  Binary:     $PYTHON"
echo "  pyperf args: $PYPERF_ARGS"
echo "  Start:      $(date)"
echo "============================================"
echo ""

# Clean previous results
rm -rf "$RESULTS"/sandbox-*

PROFILES=(
    "disabled|sandbox-disabled|"
    "enabled_nolimits|sandbox-nolimits|--scoped"
    "size_limits_only|sandbox-size-limits|--scoped"
    "iteration_limits|sandbox-iteration|--scoped"
    "dunder_blocked|sandbox-dunder|--scoped"
    "frozen_mode|sandbox-frozen|--scoped"
    "opcode_restrict|sandbox-opcodes|--scoped"
    "full_lockdown|sandbox-full|--scoped"
)

TOTAL=${#PROFILES[@]}
IDX=0
FAILED=0

for entry in "${PROFILES[@]}"; do
    IFS='|' read -r profile label scoped <<< "$entry"
    IDX=$((IDX + 1))
    echo "=== [$IDX/$TOTAL] $label ($profile) ==="

    CMD="$RUNNER --python $PYTHON --profile $profile --label $label"
    [ -n "$scoped" ] && CMD="$CMD $scoped"
    CMD="$CMD -- $PYPERF_ARGS --quiet"

    if eval "$CMD"; then
        echo ""
    else
        echo "  *** FAILED ***"
        echo ""
        FAILED=$((FAILED + 1))
    fi
done

echo "============================================"
echo " Generating report..."
echo "============================================"

COMPARE_DIRS=""
for entry in "${PROFILES[@]}"; do
    IFS='|' read -r _ label _ <<< "$entry"
    [ "$label" = "sandbox-disabled" ] && continue
    COMPARE_DIRS="$COMPARE_DIRS $RESULTS/$label"
done

../../python report.py \
    --baseline-dir "$RESULTS/sandbox-disabled" \
    --compare-dir $COMPARE_DIRS \
    --output BENCHMARK-REPORT.md

echo ""
echo "============================================"
echo " Done: $(date)"
echo " Report: Tools/sandbox_benchmarks/BENCHMARK-REPORT.md"
echo " Failed: $FAILED / $TOTAL"
echo "============================================"

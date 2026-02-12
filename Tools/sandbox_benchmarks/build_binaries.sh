#!/bin/bash
# Builds both standard CPython and sandboxed CPython binaries for benchmarking.
#
# Usage:
#   ./build_binaries.sh [--install-dir /path] [--jobs N] [--no-pgo]
#
# The script uses git worktrees to build both versions in parallel-friendly
# directories without interfering with the current working tree.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Defaults
INSTALL_DIR="/tmp/sandbox-bench"
JOBS="$(nproc 2>/dev/null || echo 4)"
PGO_FLAG="--enable-optimizations"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install-dir)
            INSTALL_DIR="$2"
            shift 2
            ;;
        --jobs)
            JOBS="$2"
            shift 2
            ;;
        --no-pgo)
            PGO_FLAG=""
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--install-dir DIR] [--jobs N] [--no-pgo]"
            echo ""
            echo "Options:"
            echo "  --install-dir DIR  Installation directory (default: /tmp/sandbox-bench)"
            echo "  --jobs N           Parallel make jobs (default: nproc)"
            echo "  --no-pgo           Skip PGO (faster build, less representative perf)"
            echo ""
            echo "Builds:"
            echo "  \$INSTALL_DIR/standard/bin/python3  - Standard CPython v3.11.14"
            echo "  \$INSTALL_DIR/sandbox/bin/python3   - Sandbox CPython (msbrogli/sandbox)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

echo "========================================"
echo "Sandbox Benchmark Binary Builder"
echo "========================================"
echo "  Repository:   $REPO_DIR"
echo "  Install dir:  $INSTALL_DIR"
echo "  Jobs:         $JOBS"
echo "  PGO:          ${PGO_FLAG:-disabled}"
echo "========================================"
echo ""

mkdir -p "$INSTALL_DIR"

# ============================================================
# 1. Build standard CPython from v3.11.14 tag
# ============================================================
echo "[1/2] Building standard CPython (v3.11.14)..."

STANDARD_SRC="$INSTALL_DIR/src-standard"
STANDARD_PREFIX="$INSTALL_DIR/standard"

# Create or update worktree
if [ ! -d "$STANDARD_SRC" ]; then
    echo "  Creating worktree for v3.11.14..."
    cd "$REPO_DIR"
    git worktree add "$STANDARD_SRC" v3.11.14 2>/dev/null || {
        echo "  Warning: worktree already exists or tag not found, trying checkout..."
        if [ -d "$STANDARD_SRC" ]; then
            cd "$STANDARD_SRC"
            git checkout v3.11.14
        else
            echo "  Error: Cannot create worktree for v3.11.14" >&2
            echo "  Make sure the tag exists: git tag -l 'v3.11*'" >&2
            exit 1
        fi
    }
fi

cd "$STANDARD_SRC"

if [ ! -f "$STANDARD_PREFIX/bin/python3" ]; then
    echo "  Configuring..."
    ./configure --prefix="$STANDARD_PREFIX" $PGO_FLAG --quiet 2>&1 | tail -5

    echo "  Building (this may take a while with PGO)..."
    make -j"$JOBS" 2>&1 | tail -3

    echo "  Installing..."
    make install 2>&1 | tail -3

    echo "  Installing pyperf..."
    "$STANDARD_PREFIX/bin/python3" -m pip install --quiet pyperf
else
    echo "  Already built, skipping. (Remove $STANDARD_PREFIX to rebuild)"
fi

echo "  Standard Python: $STANDARD_PREFIX/bin/python3"
"$STANDARD_PREFIX/bin/python3" --version
echo ""

# ============================================================
# 2. Build sandbox CPython from msbrogli/sandbox branch
# ============================================================
echo "[2/2] Building sandbox CPython (msbrogli/sandbox)..."

SANDBOX_SRC="$INSTALL_DIR/src-sandbox"
SANDBOX_PREFIX="$INSTALL_DIR/sandbox"

# Create or update worktree
if [ ! -d "$SANDBOX_SRC" ]; then
    echo "  Creating worktree for msbrogli/sandbox..."
    cd "$REPO_DIR"
    git worktree add "$SANDBOX_SRC" msbrogli/sandbox 2>/dev/null || {
        echo "  Warning: worktree already exists, trying checkout..."
        if [ -d "$SANDBOX_SRC" ]; then
            cd "$SANDBOX_SRC"
            git checkout msbrogli/sandbox
        else
            echo "  Error: Cannot create worktree for msbrogli/sandbox" >&2
            exit 1
        fi
    }
fi

cd "$SANDBOX_SRC"

if [ ! -f "$SANDBOX_PREFIX/bin/python3" ]; then
    echo "  Configuring..."
    ./configure --prefix="$SANDBOX_PREFIX" $PGO_FLAG --quiet 2>&1 | tail -5

    echo "  Building (this may take a while with PGO)..."
    make -j"$JOBS" 2>&1 | tail -3

    echo "  Installing..."
    make install 2>&1 | tail -3

    echo "  Installing pyperf..."
    "$SANDBOX_PREFIX/bin/python3" -m pip install --quiet pyperf
else
    echo "  Already built, skipping. (Remove $SANDBOX_PREFIX to rebuild)"
fi

echo "  Sandbox Python: $SANDBOX_PREFIX/bin/python3"
"$SANDBOX_PREFIX/bin/python3" --version
echo ""

# ============================================================
# Summary
# ============================================================
echo "========================================"
echo "Build complete!"
echo "========================================"
echo ""
echo "Standard: $STANDARD_PREFIX/bin/python3"
echo "Sandbox:  $SANDBOX_PREFIX/bin/python3"
echo ""
echo "Example benchmark commands:"
echo ""
echo "  # 1. Standard baseline"
echo "  ./run_benchmarks.py --python $STANDARD_PREFIX/bin/python3 --profile disabled --label standard"
echo ""
echo "  # 2. Sandbox disabled"
echo "  ./run_benchmarks.py --python $SANDBOX_PREFIX/bin/python3 --profile disabled --label sandbox-disabled"
echo ""
echo "  # 3. Sandbox with full lockdown"
echo "  ./run_benchmarks.py --python $SANDBOX_PREFIX/bin/python3 --profile full_lockdown --label sandbox-full --scoped"
echo ""
echo "  # Generate report"
echo "  ./report.py --baseline-dir results/standard --compare-dir results/sandbox-disabled results/sandbox-full"

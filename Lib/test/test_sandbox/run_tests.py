#!/usr/bin/env python3
"""Test runner for sandbox tests with support for dangerous test separation.

This module provides three test running modes:
1. safe    - Run only non-dangerous tests (default)
2. dangerous - Run only dangerous tests (files ending in _dangerous.py)
3. all    - Run all tests: safe first, then dangerous (stops if safe tests fail)

Usage:
    python -m test.test_sandbox.run_tests [mode] [options]

    # Run only safe tests (default)
    python -m test.test_sandbox.run_tests
    python -m test.test_sandbox.run_tests safe

    # Run only dangerous tests
    python -m test.test_sandbox.run_tests dangerous

    # Run all tests (safe first, then dangerous)
    python -m test.test_sandbox.run_tests all

    # With verbosity
    python -m test.test_sandbox.run_tests safe -v
    python -m test.test_sandbox.run_tests all --verbose

Environment Variables:
    SANDBOX_TEST_MODE: Override the test mode ('safe', 'dangerous', 'all')

Dangerous Tests:
    Tests in files ending with '_dangerous.py' are considered dangerous.
    These tests may hang or consume excessive resources if sandbox limits
    are not working correctly. They should only be run after safe tests pass.
"""

import argparse
import os
import sys
import unittest
from enum import Enum
from typing import List, Optional


class TestMode(Enum):
    """Test execution modes."""
    SAFE = "safe"
    DANGEROUS = "dangerous"
    ALL = "all"


# Pattern suffix for dangerous test files
DANGEROUS_SUFFIX = "_dangerous.py"


def get_test_dir() -> str:
    """Get the test_sandbox directory path."""
    return os.path.dirname(os.path.abspath(__file__))


def discover_test_files(test_dir: str) -> tuple[List[str], List[str]]:
    """Discover and categorize test files.

    Returns:
        Tuple of (safe_files, dangerous_files) where each is a list of
        module names (without .py extension).
    """
    safe_files = []
    dangerous_files = []

    for filename in sorted(os.listdir(test_dir)):
        if not filename.startswith("test") or not filename.endswith(".py"):
            continue
        if filename == "run_tests.py":
            continue

        module_name = filename[:-3]  # Remove .py

        if filename.endswith(DANGEROUS_SUFFIX):
            dangerous_files.append(module_name)
        else:
            safe_files.append(module_name)

    return safe_files, dangerous_files


def load_tests_from_modules(test_dir: str, module_names: List[str]) -> unittest.TestSuite:
    """Load tests from specific modules.

    Args:
        test_dir: Path to the test directory
        module_names: List of module names to load (without .py)

    Returns:
        TestSuite containing all tests from the specified modules
    """
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Ensure test directory is in path
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)

    # Get the parent directory for proper imports
    parent_dir = os.path.dirname(test_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    for module_name in module_names:
        try:
            # Import as test.test_sandbox.module_name
            full_module_name = f"test.test_sandbox.{module_name}"
            module_tests = loader.loadTestsFromName(full_module_name)
            suite.addTests(module_tests)
        except Exception as e:
            print(f"Warning: Failed to load {module_name}: {e}", file=sys.stderr)

    return suite


def run_test_suite(suite: unittest.TestSuite, verbosity: int = 1) -> unittest.TestResult:
    """Run a test suite and return the result.

    Args:
        suite: TestSuite to run
        verbosity: Verbosity level (0=quiet, 1=normal, 2=verbose)

    Returns:
        TestResult object with test outcomes
    """
    runner = unittest.TextTestRunner(verbosity=verbosity)
    return runner.run(suite)


def run_tests(mode: TestMode, verbosity: int = 1) -> bool:
    """Run tests according to the specified mode.

    Args:
        mode: Which tests to run (SAFE, DANGEROUS, or ALL)
        verbosity: Verbosity level for test output

    Returns:
        True if all tests passed, False otherwise
    """
    test_dir = get_test_dir()
    safe_files, dangerous_files = discover_test_files(test_dir)

    if mode == TestMode.SAFE:
        print(f"=" * 70)
        print(f"Running SAFE tests ({len(safe_files)} test files)")
        print(f"=" * 70)

        if not safe_files:
            print("No safe test files found.")
            return True

        suite = load_tests_from_modules(test_dir, safe_files)
        result = run_test_suite(suite, verbosity)
        return result.wasSuccessful()

    elif mode == TestMode.DANGEROUS:
        print(f"=" * 70)
        print(f"Running DANGEROUS tests ({len(dangerous_files)} test files)")
        print(f"=" * 70)

        if not dangerous_files:
            print("No dangerous test files found.")
            return True

        suite = load_tests_from_modules(test_dir, dangerous_files)
        result = run_test_suite(suite, verbosity)
        return result.wasSuccessful()

    elif mode == TestMode.ALL:
        # Run safe tests first
        print(f"=" * 70)
        print(f"Phase 1: Running SAFE tests ({len(safe_files)} test files)")
        print(f"=" * 70)

        if safe_files:
            safe_suite = load_tests_from_modules(test_dir, safe_files)
            safe_result = run_test_suite(safe_suite, verbosity)

            if not safe_result.wasSuccessful():
                print()
                print(f"=" * 70)
                print("SAFE tests FAILED - skipping dangerous tests")
                print(f"=" * 70)
                return False
        else:
            print("No safe test files found.")

        # Run dangerous tests only if safe tests passed
        print()
        print(f"=" * 70)
        print(f"Phase 2: Running DANGEROUS tests ({len(dangerous_files)} test files)")
        print(f"=" * 70)

        if not dangerous_files:
            print("No dangerous test files found.")
            return True

        dangerous_suite = load_tests_from_modules(test_dir, dangerous_files)
        dangerous_result = run_test_suite(dangerous_suite, verbosity)

        # Print summary
        print()
        print(f"=" * 70)
        print("TEST SUMMARY")
        print(f"=" * 70)
        if safe_files:
            safe_status = "PASSED" if safe_result.wasSuccessful() else "FAILED"
            print(f"  Safe tests:      {safe_status}")
        if dangerous_files:
            dangerous_status = "PASSED" if dangerous_result.wasSuccessful() else "FAILED"
            print(f"  Dangerous tests: {dangerous_status}")

        return dangerous_result.wasSuccessful()

    return False


def main(args: Optional[List[str]] = None) -> int:
    """Main entry point for the test runner.

    Args:
        args: Command line arguments (defaults to sys.argv[1:])

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    parser = argparse.ArgumentParser(
        description="Run sandbox tests with dangerous test separation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "mode",
        nargs="?",
        default="safe",
        choices=["safe", "dangerous", "all"],
        help="Test mode: 'safe' (default), 'dangerous', or 'all'"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output (show each test name)"
    )
    parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Quiet output (minimal output)"
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List test files by category and exit"
    )

    parsed_args = parser.parse_args(args)

    # Check environment variable override
    env_mode = os.environ.get("SANDBOX_TEST_MODE")
    if env_mode and env_mode.lower() in ("safe", "dangerous", "all"):
        mode_str = env_mode.lower()
    else:
        mode_str = parsed_args.mode

    mode = TestMode(mode_str)

    # Handle --list
    if parsed_args.list:
        test_dir = get_test_dir()
        safe_files, dangerous_files = discover_test_files(test_dir)

        print("Safe test files:")
        for f in safe_files:
            print(f"  {f}.py")
        print()
        print("Dangerous test files:")
        for f in dangerous_files:
            print(f"  {f}.py")
        if not dangerous_files:
            print("  (none)")
        return 0

    # Determine verbosity
    if parsed_args.quiet:
        verbosity = 0
    elif parsed_args.verbose:
        verbosity = 2
    else:
        verbosity = 1

    # Run tests
    success = run_tests(mode, verbosity)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())

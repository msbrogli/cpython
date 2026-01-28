"""Integration tests for sandbox functionality."""

import subprocess
import sys
import unittest

from test.test_sandbox import _get_settable_limits


class IntegrationTests(unittest.TestCase):
    """Integration tests for sandbox functionality."""

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_limits(**self.original_limits)

    def test_sandbox_exec_with_all_limits(self):
        """Test running sandboxed code with all limit types."""
        code = '''
import sys
sys.sandbox.set_limits(
    max_int_digits=100,
    max_str_length=10000,
    max_list_size=1000,
    max_statements=10000,
    max_allocations=5000,
)
sys.sandbox.reset_counts()
sys.sandbox.enter_scope()
try:
    exec("""
result = []
for i in range(100):
    result.append(i * 2)
total = sum(result)
""")
    sys.exit(0)  # Success
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    sys.exit(1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Sandboxed exec failed: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()

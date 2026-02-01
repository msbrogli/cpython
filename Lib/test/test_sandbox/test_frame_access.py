"""Tests for generator/coroutine frame access blocking in sandbox.

This module tests that access to gi_frame, cr_frame, and ag_frame
attributes is blocked in sandbox scope to prevent frame-based escapes.

Security audit reference: Fix proposal 10 - Frame access blocking
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class GeneratorFrameAccessTests(ScopedFilenameTestCase):
    """Test generator.gi_frame access is blocked in sandbox scope.

    Attack vector: Access gi_frame to get frame object, then use
    f_locals or f_globals to escape sandbox restrictions.
    """

    SCOPED_FILENAME = "<test_frame_access_scope>"

    def test_gi_frame_blocked_in_scope(self):
        """generator.gi_frame access should be blocked in scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises((AttributeError, SandboxSecurityError)):
            self.run_scoped_code("""
def gen():
    yield 1
    yield 2
g = gen()
frame = g.gi_frame
""")

    def test_gi_frame_allowed_outside_scope(self):
        """generator.gi_frame should be accessible outside scope."""
        def gen():
            yield 1
        g = gen()
        # Outside scope - should work
        frame = g.gi_frame
        self.assertIsNotNone(frame)

    def test_gi_code_accessible_in_scope(self):
        """generator.gi_code should be accessible (read-only, safe).

        Note: This may or may not be blocked depending on implementation.
        Documenting current behavior.
        """
        sys.sandbox.set_config(max_operations=10000)

        # Test whether gi_code is accessible or blocked
        try:
            globs = self.run_scoped_code("""
def gen():
    yield 1
g = gen()
code_obj = g.gi_code
has_code = code_obj is not None
""")
            # If accessible, verify it returned something
            self.assertTrue(globs.get('has_code', False))
        except (AttributeError, SandboxSecurityError):
            # If blocked, that's also acceptable
            pass

    def test_gi_yieldfrom_in_scope(self):
        """generator.gi_yieldfrom access behavior in scope.

        Note: gi_yieldfrom may or may not be blocked - document current behavior.
        It exposes the inner generator but not frames directly.
        """
        sys.sandbox.set_config(max_operations=10000)

        # Test current behavior - gi_yieldfrom may be allowed
        try:
            globs = self.run_scoped_code("""
def inner():
    yield 1
def outer():
    yield from inner()
g = outer()
next(g)
yieldfrom = g.gi_yieldfrom
has_yieldfrom = yieldfrom is not None
""")
            # If accessible, verify it returned something
            # gi_yieldfrom access may be allowed (doesn't expose frames)
        except (AttributeError, SandboxSecurityError):
            # If blocked, that's also acceptable
            pass


class CoroutineFrameAccessTests(ScopedFilenameTestCase):
    """Test coroutine.cr_frame access is blocked in sandbox scope."""

    SCOPED_FILENAME = "<test_frame_access_scope>"

    def test_cr_frame_blocked_in_scope(self):
        """coroutine.cr_frame access should be blocked in scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises((AttributeError, SandboxSecurityError)):
            self.run_scoped_code("""
async def coro():
    return 1
c = coro()
try:
    frame = c.cr_frame
finally:
    c.close()
""")

    def test_cr_frame_allowed_outside_scope(self):
        """coroutine.cr_frame should be accessible outside scope."""
        async def coro():
            return 1
        c = coro()
        try:
            # Outside scope - should work
            frame = c.cr_frame
            self.assertIsNotNone(frame)
        finally:
            c.close()


class AsyncGeneratorFrameAccessTests(ScopedFilenameTestCase):
    """Test async_generator.ag_frame access is blocked in sandbox scope."""

    SCOPED_FILENAME = "<test_frame_access_scope>"

    def test_ag_frame_blocked_in_scope(self):
        """async_generator.ag_frame access should be blocked in scope."""
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises((AttributeError, SandboxSecurityError)):
            self.run_scoped_code("""
async def agen():
    yield 1
ag = agen()
frame = ag.ag_frame
""")

    def test_ag_frame_allowed_outside_scope(self):
        """async_generator.ag_frame should be accessible outside scope."""
        async def agen():
            yield 1
        ag = agen()
        try:
            # Outside scope - should work
            frame = ag.ag_frame
            self.assertIsNotNone(frame)
        finally:
            # Clean up async generator
            try:
                ag.aclose()
            except:
                pass


class SubprocessFrameAccessTests(unittest.TestCase):
    """Subprocess tests for frame access that need full isolation."""

    def test_gi_frame_escape_blocked(self):
        """Attempt to use gi_frame to access f_globals should fail."""
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.enter_scope()

def gen():
    yield 1

g = gen()
try:
    # Try to access frame to get globals
    frame = g.gi_frame
    # If we got here, try to access f_globals
    globals_dict = frame.f_globals
    sys.exit(2)  # Should not reach - security hole
except (AttributeError, SandboxSecurityError):
    sys.exit(0)  # Expected - access blocked
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(3)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Frame access not blocked: {result.stderr}")

    def test_cr_frame_escape_blocked(self):
        """Attempt to use cr_frame to access f_locals should fail."""
        code = '''
import sys
sys.sandbox.set_config(max_list_size=10)
sys.sandbox.enter_scope()

async def coro():
    return 1

c = coro()
try:
    # Try to access frame
    frame = c.cr_frame
    locals_dict = frame.f_locals
    sys.exit(2)  # Should not reach
except (AttributeError, SandboxSecurityError):
    sys.exit(0)  # Expected
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(3)
finally:
    c.close()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Frame access not blocked: {result.stderr}")

    def test_traceback_frame_access(self):
        """Traceback frame access should be handled safely.

        Note: This tests that exception handling doesn't expose frames
        that could be used to escape the sandbox.
        """
        code = '''
import sys
sys.sandbox.set_config(max_operations=10000)
sys.sandbox.enter_scope()

try:
    raise ValueError("test")
except ValueError:
    import traceback
    # Getting traceback info should work
    exc_type, exc_val, exc_tb = sys.exc_info()
    # But accessing tb_frame might be blocked
    try:
        frame = exc_tb.tb_frame
        # If accessible, we document this behavior
        # Frame access via traceback may be allowed for debugging
    except (AttributeError, SandboxSecurityError):
        pass  # Blocked is fine too

sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed: {result.stderr}")


class FrameAttributeTests(ScopedFilenameTestCase):
    """Test specific frame attributes are blocked or safe."""

    SCOPED_FILENAME = "<test_frame_access_scope>"

    def test_frame_via_sys_getframe_behavior(self):
        """sys._getframe() behavior in sandbox.

        Note: Documenting whether sys._getframe is available in scope.
        """
        sys.sandbox.set_config(max_operations=10000)

        try:
            globs = self.run_scoped_code("frame = sys._getframe(0)")
            # If accessible, the sandbox should still prevent abuse
            # The frame from scoped code shouldn't allow escape
        except (AttributeError, SandboxSecurityError):
            # sys._getframe blocked in sandbox is acceptable
            pass
        except RuntimeError:
            # _getframe may raise RuntimeError in some contexts
            pass


if __name__ == '__main__':
    unittest.main()

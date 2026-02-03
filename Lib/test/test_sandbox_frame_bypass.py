"""Tests for sandbox frame introspection bypass vulnerabilities.

This module tests security fixes for:
1. sys._getframe() - blocks frame introspection from sandbox scope
2. sys._current_frames() - blocks access to all thread frames from sandbox scope
3. sys._current_exceptions() - blocks access to exception info from sandbox scope
4. generator.send() - ensures send() counts toward iteration limits

Tests are designed to:
- FAIL if the vulnerability exists (bypass works)
- PASS if protection is in place (bypass blocked with SandboxSecurityError or limits enforced)

IMPORTANT: Tests save function references BEFORE entering sandbox scope to bypass
module access restrictions, simulating a realistic attack where the attacker has
access to these functions (e.g., through a reference passed from trusted code).

Tests run in subprocesses to avoid sandbox scope conflicts between tests.
"""

import subprocess
import sys
import unittest


def run_sandbox_test(code: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


class SysGetframeBypassTest(unittest.TestCase):
    """Test that sys._getframe() is blocked in sandbox scope.

    sys._getframe() returns frame objects which expose f_locals, f_globals,
    f_back, and f_code - allowing complete information disclosure from
    trusted code that invoked the sandbox.
    """

    def test_getframe_blocked_in_sandbox_scope(self):
        """sys._getframe() should be blocked when called from sandbox scope."""
        code = '''
import sys
# Save reference BEFORE entering scope to bypass module restrictions
_getframe = sys._getframe
sys.sandbox.module_access_restrict_mode = 0  # Ensure we test the function itself
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')
try:
    frame = _getframe(0)
    print(f"FAIL: sys._getframe() returned frame with locals: {list(frame.f_locals.keys())[:3]}")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_getframe_with_depth_blocked(self):
        """sys._getframe(depth) should be blocked regardless of depth argument."""
        code = '''
import sys
_getframe = sys._getframe
sys.sandbox.module_access_restrict_mode = 0

def inner():
    sys.sandbox.enable()
    sys.sandbox.add_filename('<string>')
    try:
        frame = _getframe(1)  # Try to get caller's frame
        print(f"FAIL: sys._getframe(1) returned frame: {frame.f_code.co_name}")
    except SandboxSecurityError:
        print("PASS")

inner()
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_getframe_f_locals_leak_prevented(self):
        """Sandboxed code should not be able to read caller's locals via _getframe().

        This is the primary attack vector: sandboxed code calls sys._getframe(1)
        to get the trusted caller's frame and reads f_locals to leak secrets.
        """
        code = '''
import sys
_getframe = sys._getframe

def trusted_code_with_secrets():
    api_key = "SECRET_API_KEY_12345"
    password = "hunter2"
    database_url = "postgres://user:pass@host/db"

    # Enter sandbox scope
    sys.sandbox.module_access_restrict_mode = 0
    sys.sandbox.enable()
    sys.sandbox.add_filename('<string>')

    # This simulates malicious sandboxed code trying to leak secrets
    try:
        frame = _getframe(0)
        # If we get here, check if we can read locals
        leaked = frame.f_locals
        if "api_key" in leaked:
            print(f"FAIL: leaked secrets including api_key")
        else:
            print(f"FAIL: got frame but no secrets visible")
    except SandboxSecurityError:
        print("PASS")

trusted_code_with_secrets()
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_getframe_call_stack_traversal_blocked(self):
        """Walking the call stack via f_back should be prevented."""
        code = '''
import sys
_getframe = sys._getframe

def deep_function():
    sys.sandbox.module_access_restrict_mode = 0
    sys.sandbox.enable()
    sys.sandbox.add_filename('<string>')

    try:
        frame = _getframe(0)
        # If this succeeds, try walking the stack
        secrets = {}
        while frame is not None:
            secrets[frame.f_code.co_name] = list(frame.f_locals.keys())
            frame = frame.f_back
        print(f"FAIL: walked stack and collected: {list(secrets.keys())}")
    except SandboxSecurityError:
        print("PASS")

def middle():
    secret = "middle_secret"
    deep_function()

def outer():
    outer_secret = "outer_secret"
    middle()

outer()
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_getframe_allowed_outside_sandbox_scope(self):
        """sys._getframe() should work normally outside sandbox scope."""
        code = '''
import sys
# Sandbox enabled but no filename registered - not in scope
sys.sandbox.enable()
frame = sys._getframe(0)
if frame is not None and frame.f_code.co_name == '<module>':
    print("PASS")
else:
    print(f"FAIL: frame={frame}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SysCurrentFramesBypassTest(unittest.TestCase):
    """Test that sys._current_frames() is blocked in sandbox scope.

    sys._current_frames() returns frame objects for ALL threads without
    sandbox check. This is even more dangerous as it can read locals
    from any thread in the process.
    """

    def test_current_frames_blocked_in_sandbox_scope(self):
        """sys._current_frames() should be blocked in sandbox scope."""
        code = '''
import sys
_current_frames = sys._current_frames
sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')
try:
    frames = _current_frames()
    print(f"FAIL: sys._current_frames() returned {len(frames)} frames")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_current_frames_thread_leak_prevented(self):
        """Sandboxed code should not leak data from other threads."""
        code = '''
import sys
import threading
import time

_current_frames = sys._current_frames
thread_secret = None
barrier = threading.Barrier(2)

def other_thread():
    global thread_secret
    thread_secret = "THREAD_SECRET_DATA"
    barrier.wait()  # Signal main thread
    time.sleep(1)  # Keep thread alive

t = threading.Thread(target=other_thread)
t.start()
barrier.wait()  # Wait for thread to set secret

sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')
try:
    all_frames = _current_frames()
    # If we get here, check if we can read other thread's data
    for thread_id, frame in all_frames.items():
        while frame:
            if 'thread_secret' in frame.f_locals:
                print(f"FAIL: leaked thread secret")
                break
            frame = frame.f_back
    else:
        print(f"FAIL: got {len(all_frames)} frames")
except SandboxSecurityError:
    print("PASS")
finally:
    t.join(timeout=2)
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_current_frames_allowed_outside_scope(self):
        """sys._current_frames() should work normally outside sandbox scope."""
        code = '''
import sys
import threading
# Sandbox enabled but no filename registered - not in scope
sys.sandbox.enable()
frames = sys._current_frames()
if threading.current_thread().ident in frames:
    print("PASS")
else:
    print("FAIL")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SysCurrentExceptionsBypassTest(unittest.TestCase):
    """Test that sys._current_exceptions() is blocked in sandbox scope.

    sys._current_exceptions() returns exception info including traceback
    objects which expose frame information.
    """

    def test_current_exceptions_blocked_in_sandbox_scope(self):
        """sys._current_exceptions() should be blocked in sandbox scope."""
        code = '''
import sys
_current_exceptions = sys._current_exceptions
sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')
try:
    exceptions = _current_exceptions()
    print(f"FAIL: sys._current_exceptions() returned {type(exceptions)}")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_current_exceptions_frame_leak_prevented(self):
        """Exception tracebacks should not leak frame data in sandbox scope."""
        code = '''
import sys
import threading
import time

_current_exceptions = sys._current_exceptions
barrier = threading.Barrier(2)
thread_ready = threading.Event()

def thread_with_exception():
    secret = "EXCEPTION_THREAD_SECRET"
    try:
        raise ValueError("test error")
    except:
        barrier.wait()  # Signal that exception is active
        thread_ready.set()
        time.sleep(1)  # Keep exception context alive

t = threading.Thread(target=thread_with_exception)
t.start()
barrier.wait()
thread_ready.wait()

sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')
try:
    exceptions = _current_exceptions()
    print(f"FAIL: got {len(exceptions)} exception contexts")
except SandboxSecurityError:
    print("PASS")
finally:
    t.join(timeout=2)
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_current_exceptions_allowed_outside_scope(self):
        """sys._current_exceptions() should work normally outside sandbox scope."""
        code = '''
import sys
# Sandbox enabled but no filename registered - not in scope
sys.sandbox.enable()
exceptions = sys._current_exceptions()
# Should return dict (possibly empty if no active exceptions)
if isinstance(exceptions, dict):
    print("PASS")
else:
    print(f"FAIL: {type(exceptions)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class GeneratorSendIterationBypassTest(unittest.TestCase):
    """Test that generator.send() counts toward iteration limits.

    The sandbox wraps iterators via _PySandbox_WrapIterator() when
    PyObject_GetIter() is called. But generator.send() calls gen_send_ex2()
    directly, bypassing iteration counting.
    """

    def test_generator_send_counted_toward_iterations(self):
        """generator.send() should count toward max_iterations limit."""
        code = '''
import sys
sys.sandbox.max_iterations = 100
sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')

def infinite_gen():
    i = 0
    while True:
        yield i
        i += 1

gen = infinite_gen()
next(gen)  # Initialize generator

try:
    # Try to bypass iteration limit via send()
    for _ in range(200):
        gen.send(None)
    print("FAIL: exceeded iteration limit via send()")
except SandboxRuntimeError as e:
    if "iteration" in str(e).lower():
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
except Exception as e:
    # Accept any sandbox-related error as protection
    if "Sandbox" in type(e).__name__:
        print(f"PASS: {type(e).__name__}")
    else:
        print(f"FAIL: unexpected {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_generator_send_vs_next_equal_counting(self):
        """send() and next() should be counted equally toward limits."""
        # Test next() counting
        code_next = '''
import sys
sandbox = sys.sandbox

sandbox.max_iterations = 50
sandbox.module_access_restrict_mode = 0
sandbox.enable()
sandbox.add_filename('<string>')

def gen():
    i = 0
    while True:
        yield i
        i += 1

g = gen()
count = 0
try:
    for i in range(100):
        next(g)
        count += 1
except:
    pass
print(count)
'''
        # Test send() counting
        code_send = '''
import sys
sandbox = sys.sandbox

sandbox.max_iterations = 50
sandbox.module_access_restrict_mode = 0
sandbox.enable()
sandbox.add_filename('<string>')

def gen():
    i = 0
    while True:
        yield i
        i += 1

g = gen()
next(g)  # Initialize
count = 0
try:
    for i in range(100):
        g.send(None)
        count += 1
except:
    pass
print(count)
'''
        rc_next, out_next, _ = run_sandbox_test(code_next)
        rc_send, out_send, _ = run_sandbox_test(code_send)

        count_next = int(out_next.strip())
        count_send = int(out_send.strip())
        # Both should hit limit around same count (within a few iterations)
        # Account for the initial next() call in send test
        if abs(count_next - count_send) > 10:
            self.fail(f"next()={count_next}, send()={count_send}")

    def test_send_with_no_limit(self):
        """send() should work normally when no iteration limit is set."""
        code = '''
import sys
# max_iterations=0 means no limit
sys.sandbox.max_iterations = 0
sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')

def gen():
    for i in range(5):
        received = yield i
        if received is not None:
            yield f"received: {received}"

g = gen()
results = []
results.append(next(g))
results.append(g.send("hello"))
results.append(next(g))

if results == [0, "received: hello", 1]:
    print("PASS")
else:
    print(f"FAIL: {results}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_send_bypass_attack_blocked(self):
        """Direct send() bypass attack should be blocked.

        Attack: Use generator.send() in a tight loop to bypass max_iterations
        because send() bypasses the iterator wrapper.
        """
        code = '''
import sys
sys.sandbox.max_iterations = 50
sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')

def infinite():
    while True:
        yield

g = infinite()
next(g)  # Start

# This attack attempts to loop indefinitely via send()
iteration_count = 0
try:
    while True:
        g.send(None)
        iteration_count += 1
        if iteration_count > 1000:
            print(f"FAIL: bypassed limit, reached {iteration_count} iterations")
            break
except:
    if iteration_count < 100:
        print(f"PASS: stopped at {iteration_count}")
    else:
        print(f"FAIL: too many iterations: {iteration_count}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class CombinedFrameBypassTest(unittest.TestCase):
    """Test combined attack scenarios using frame introspection."""

    def test_full_exploit_chain_blocked(self):
        """Full exploit chain using _getframe should be blocked.

        Attack chain:
        1. Use sys._getframe() to get trusted code's frame
        2. Walk f_back chain to find frames with sensitive data
        3. Extract f_locals and f_globals from each frame
        4. Look for credentials, API keys, database connections, etc.
        """
        code = '''
import sys
_getframe = sys._getframe

# Simulate trusted application code
class DatabaseConnection:
    def __init__(self, conn_str):
        self.conn_str = conn_str

def trusted_application():
    db_password = "super_secret_db_password"
    api_token = "sk-live-abcdef123456"
    db = DatabaseConnection("postgres://admin:secret@localhost/prod")

    # Now enter sandbox to run untrusted code
    sys.sandbox.module_access_restrict_mode = 0
    sys.sandbox.enable()
    sys.sandbox.add_filename('<string>')

    # Malicious code tries the exploit chain
    try:
        frame = _getframe(0)
        leaked_data = {}
        while frame:
            for name, value in frame.f_locals.items():
                if isinstance(value, str) and len(value) > 5:
                    leaked_data[name] = value[:20]
            frame = frame.f_back

        if leaked_data:
            print(f"FAIL: leaked data keys: {list(leaked_data.keys())}")
        else:
            print("FAIL: got frames but no data")
    except SandboxSecurityError:
        print("PASS")

trusted_application()
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_all_frame_methods_blocked(self):
        """All frame introspection methods should be blocked in sandbox scope."""
        code = '''
import sys
# Save all references before entering scope
_getframe = sys._getframe
_current_frames = sys._current_frames
_current_exceptions = sys._current_exceptions

sys.sandbox.module_access_restrict_mode = 0
sys.sandbox.enable()
sys.sandbox.add_filename('<string>')

methods_blocked = []

try:
    _getframe(0)
except SandboxSecurityError:
    methods_blocked.append("_getframe")
except Exception as e:
    pass  # Other errors don't count as blocked

try:
    _current_frames()
except SandboxSecurityError:
    methods_blocked.append("_current_frames")
except Exception as e:
    pass

try:
    _current_exceptions()
except SandboxSecurityError:
    methods_blocked.append("_current_exceptions")
except Exception as e:
    pass

if len(methods_blocked) == 3:
    print("PASS")
else:
    print(f"FAIL: only blocked {methods_blocked}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


if __name__ == '__main__':
    unittest.main()

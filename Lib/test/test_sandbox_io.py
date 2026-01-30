"""Tests for sandbox allow_io flag.

This module tests the allow_io flag which controls I/O operations
(file, socket, raw fd) within sandbox scope.

Tests run in subprocesses to avoid sandbox scope conflicts between tests.
"""

import subprocess
import sys
import unittest


def run_sandbox_test(code: str) -> tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=10
    )
    return result.returncode, result.stdout, result.stderr


class AllowIOPropertyTest(unittest.TestCase):
    """Test allow_io property getter/setter."""

    def test_default_value_is_false(self):
        """allow_io should default to False after reset."""
        code = '''
import sys
sys.sandbox.reset()
if sys.sandbox.allow_io == False:
    print("PASS")
else:
    print(f"FAIL: allow_io={sys.sandbox.allow_io}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_setter_true(self):
        """allow_io should be settable to True."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.allow_io = True
if sys.sandbox.allow_io == True:
    print("PASS")
else:
    print(f"FAIL: allow_io={sys.sandbox.allow_io}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_setter_false(self):
        """allow_io should be settable to False."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.allow_io = True
sys.sandbox.allow_io = False
if sys.sandbox.allow_io == False:
    print("PASS")
else:
    print(f"FAIL: allow_io={sys.sandbox.allow_io}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class AllowIOGetSetLimitsTest(unittest.TestCase):
    """Test allow_io in get_limits/set_limits methods."""

    def test_get_limits_includes_allow_io(self):
        """get_limits() should include allow_io."""
        code = '''
import sys
sys.sandbox.reset()
limits = sys.sandbox.get_limits()
if 'allow_io' in limits and limits['allow_io'] == False:
    print("PASS")
else:
    print(f"FAIL: limits={limits}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_set_limits_allow_io_true(self):
        """set_limits(allow_io=True) should work."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.set_limits(allow_io=True)
if sys.sandbox.allow_io == True:
    print("PASS")
else:
    print(f"FAIL: allow_io={sys.sandbox.allow_io}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_set_limits_allow_io_false(self):
        """set_limits(allow_io=False) should work."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.allow_io = True
sys.sandbox.set_limits(allow_io=False)
if sys.sandbox.allow_io == False:
    print("PASS")
else:
    print(f"FAIL: allow_io={sys.sandbox.allow_io}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OpenBlockedTest(unittest.TestCase):
    """Test that open() is blocked when allow_io=False."""

    def test_open_blocked_in_scope(self):
        """open() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    f = open('/tmp/test_sandbox_io.txt', 'w')
    f.close()
    print("FAIL: open() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_open_allowed_with_allow_io_true(self):
        """open() should be allowed with allow_io=True."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = True
sys.sandbox.add_filename('<string>')
try:
    f = open('/tmp/test_sandbox_io_allowed.txt', 'w')
    f.write('test')
    f.close()
    os.remove('/tmp/test_sandbox_io_allowed.txt')
    print("PASS")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_open_allowed_outside_scope(self):
        """open() should be allowed outside sandbox scope."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.allow_io = False
# Don't add filename - not in scope
try:
    f = open('/tmp/test_sandbox_io_outside.txt', 'w')
    f.write('test')
    f.close()
    import os
    os.remove('/tmp/test_sandbox_io_outside.txt')
    print("PASS")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OsOpenBlockedTest(unittest.TestCase):
    """Test that os.open() is blocked when allow_io=False."""

    def test_os_open_blocked_in_scope(self):
        """os.open() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    fd = os.open('/tmp/test.txt', os.O_CREAT | os.O_WRONLY)
    os.close(fd)
    print("FAIL: os.open() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OsReadWriteBlockedTest(unittest.TestCase):
    """Test that os.read()/os.write() are blocked when allow_io=False."""

    def test_os_read_blocked_in_scope(self):
        """os.read() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    os.read(0, 1)
    print("FAIL: os.read() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_os_write_blocked_in_scope(self):
        """os.write() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    os.write(1, b'test')
    print("FAIL: os.write() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OsCloseBlockedTest(unittest.TestCase):
    """Test that os.close()/os.closerange() are blocked when allow_io=False."""

    def test_os_close_blocked_in_scope(self):
        """os.close() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    os.close(999)  # Invalid fd but check happens first
    print("FAIL: os.close() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_os_closerange_blocked_in_scope(self):
        """os.closerange() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    os.closerange(999, 1000)
    print("FAIL: os.closerange() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OsDupBlockedTest(unittest.TestCase):
    """Test that os.dup()/os.dup2() are blocked when allow_io=False."""

    def test_os_dup_blocked_in_scope(self):
        """os.dup() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    fd = os.dup(1)
    os.close(fd)
    print("FAIL: os.dup() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_os_dup2_blocked_in_scope(self):
        """os.dup2() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    os.dup2(1, 999)
    print("FAIL: os.dup2() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class OsPipeBlockedTest(unittest.TestCase):
    """Test that os.pipe() is blocked when allow_io=False."""

    def test_os_pipe_blocked_in_scope(self):
        """os.pipe() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import os
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('os', '')}
sys.sandbox.allowed_modules = {'os'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    r, w = os.pipe()
    os.close(r)
    os.close(w)
    print("FAIL: os.pipe() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SocketBlockedTest(unittest.TestCase):
    """Test that socket creation is blocked when allow_io=False."""

    def test_socket_blocked_in_scope(self):
        """_socket.socket() should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
import _socket
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('_socket', '')}
sys.sandbox.allowed_modules = {'_socket'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
    s.close()
    print("FAIL: socket() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_socket_allowed_with_allow_io_true(self):
        """_socket.socket() should be allowed with allow_io=True."""
        code = '''
import sys
import _socket
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('_socket', '')}
sys.sandbox.allowed_modules = {'_socket'}
sys.sandbox.allow_io = True
sys.sandbox.add_filename('<string>')
try:
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM, 0)
    s.close()
    print("PASS")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_high_level_socket_blocked_when_wrapper_in_scope(self):
        """socket.socket() should be blocked when socket.py is also in scope."""
        code = '''
import sys
import socket
sys.sandbox.reset()
sys.sandbox.allowed_imports = {('_socket', ''), ('socket', '')}
sys.sandbox.allowed_modules = {'_socket', 'socket'}
sys.sandbox.allow_io = False
sys.sandbox.add_filename(socket.__file__)  # Add socket.py to scope
sys.sandbox.add_filename('<string>')
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.close()
    print("FAIL: socket.socket() should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class FileIOBlockedTest(unittest.TestCase):
    """Test that FileIO is blocked when allow_io=False."""

    def test_fileio_blocked_in_scope(self):
        """FileIO should be blocked in sandbox scope with allow_io=False."""
        code = '''
import sys
from _io import FileIO
sys.sandbox.reset()
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    f = FileIO('/tmp/test.txt', 'w')
    f.close()
    print("FAIL: FileIO should have been blocked")
except SandboxSecurityError:
    print("PASS")
except Exception as e:
    print(f"FAIL: wrong exception {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class InMemoryIOAllowedTest(unittest.TestCase):
    """Test that in-memory I/O (StringIO, BytesIO) is allowed."""

    def test_stringio_allowed_in_scope(self):
        """StringIO should be allowed even with allow_io=False."""
        code = '''
import sys
from io import StringIO
sys.sandbox.reset()
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    s = StringIO()
    s.write('test')
    if s.getvalue() == 'test':
        print("PASS")
    else:
        print("FAIL: StringIO not working correctly")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_bytesio_allowed_in_scope(self):
        """BytesIO should be allowed even with allow_io=False."""
        code = '''
import sys
from io import BytesIO
sys.sandbox.reset()
sys.sandbox.allow_io = False
sys.sandbox.add_filename('<string>')
try:
    b = BytesIO()
    b.write(b'test')
    if b.getvalue() == b'test':
        print("PASS")
    else:
        print("FAIL: BytesIO not working correctly")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


if __name__ == '__main__':
    unittest.main()

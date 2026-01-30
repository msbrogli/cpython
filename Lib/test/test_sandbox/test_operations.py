"""Tests for opcode-based operation counting (SANDBOX_COUNT).

Tests the PyCF_SANDBOX_COUNT compile flag and the max_operations /
operation_count mechanism.
"""

import sys
import unittest


# PyCF_SANDBOX_COUNT flag value
PyCF_SANDBOX_COUNT = 0x8000
SANDBOX_FILENAME = "<sandbox-ops-test>"


def _compile_sandboxed(source, filename=SANDBOX_FILENAME):
    """Compile source with the PyCF_SANDBOX_COUNT flag."""
    return compile(source, filename, "exec", flags=PyCF_SANDBOX_COUNT)


def _run_and_count(source, max_ops=100000):
    """Compile with sandbox flag, execute, and return operation count."""
    # Disable import and module access restrictions for legacy tests
    sys.sandbox.import_restrict_mode = False
    sys.sandbox.module_access_restrict_mode = False
    sys.sandbox.set_limits(max_operations=max_ops)
    sys.sandbox.add_filename(SANDBOX_FILENAME)
    sys.sandbox.reset_counts()
    code = _compile_sandboxed(source)
    exec(code, {"__builtins__": __builtins__})
    count = sys.sandbox.get_counts()["operation_count"]
    sys.sandbox.clear_filenames()
    return count


class OperationCountingAPITests(unittest.TestCase):
    """Test the API for operation counting."""

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_scope_max_operations_in_limits(self):
        """scope_max_operations should appear in getsandboxlimits."""
        limits = sys.sandbox.get_limits()
        self.assertIn("max_operations", limits)
        self.assertEqual(limits["max_operations"], 0)

    def test_operation_count_in_counts(self):
        """operation_count should appear in getsandboxcounts."""
        counts = sys.sandbox.get_counts()
        self.assertIn("operation_count", counts)

    def test_set_scope_max_operations(self):
        """setsandboxlimits should accept scope_max_operations."""
        sys.sandbox.set_limits(max_operations=500)
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits["max_operations"], 500)

    def test_no_counting_without_flag(self):
        """Code compiled without PyCF_SANDBOX_COUNT should not be counted."""
        sys.sandbox.set_limits(max_operations=100000)
        sys.sandbox.add_filename(SANDBOX_FILENAME)
        sys.sandbox.reset_counts()
        code = compile("a = 1\nb = 2\nc = 3", SANDBOX_FILENAME, "exec")
        exec(code)
        count = sys.sandbox.get_counts()["operation_count"]
        self.assertEqual(count, 0)

    def test_no_counting_without_registered_filename(self):
        """Code with unregistered filename should not be counted."""
        sys.sandbox.set_limits(max_operations=100000)
        sys.sandbox.clear_filenames()
        sys.sandbox.reset_counts()
        code = _compile_sandboxed("a = 1", "<unregistered>")
        exec(code)
        count = sys.sandbox.get_counts()["operation_count"]
        self.assertEqual(count, 0)


class StatementOperationCountTests(unittest.TestCase):
    """Test operation counts for statement AST nodes."""

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_assign(self):
        """Assign statement counts 1."""
        self.assertEqual(_run_and_count("a = 1"), 1)

    def test_augassign(self):
        """AugAssign statement counts 1."""
        self.assertEqual(_run_and_count("a = 0\na += 1"), 2)  # Assign + AugAssign

    def test_pass(self):
        """Pass statement counts 1."""
        self.assertEqual(_run_and_count("pass"), 1)

    def test_delete(self):
        """Delete statement counts 1."""
        self.assertEqual(_run_and_count("a = 1\ndel a"), 2)  # Assign + Delete

    def test_if(self):
        """If statement counts 1."""
        self.assertEqual(_run_and_count("if True:\n    a = 1"), 2)  # If + Assign

    def test_for(self):
        """For statement counts 1 (when entered)."""
        # For(1) + Call(range)(1) + Pass*2 = 4
        self.assertEqual(_run_and_count("for _ in range(2): pass"), 4)

    def test_while(self):
        """While statement counts 1 (when entered)."""
        self.assertEqual(_run_and_count("while False: pass"), 1)  # While only

    def test_return(self):
        """Return statement counts 1."""
        # FunctionDef(1) + Call(f)(1) + Return(1) = 3
        self.assertEqual(_run_and_count("def f():\n    return 1\nf()"), 3)

    def test_try(self):
        """Try statement counts 1."""
        self.assertEqual(_run_and_count("try:\n    pass\nexcept:\n    pass"), 2)  # Try + Pass

    def test_import(self):
        """Import statement counts 1."""
        self.assertEqual(_run_and_count("import sys"), 1)

    def test_import_from(self):
        """ImportFrom statement counts 1."""
        self.assertEqual(_run_and_count("from sys import path"), 1)

    def test_assert(self):
        """Assert statement counts 1."""
        self.assertEqual(_run_and_count("assert True"), 1)

    def test_break(self):
        """Break statement counts 1."""
        # For(1) + Call(range)(1) + Break(1) = 3
        self.assertEqual(
            _run_and_count("for _ in range(1):\n    break"), 3
        )

    def test_continue(self):
        """Continue statement counts 1."""
        # For(1) + Call(range)(1) + Continue(1) = 3
        self.assertEqual(
            _run_and_count("for _ in range(1):\n    continue"), 3
        )

    def test_functiondef(self):
        """FunctionDef statement counts 1."""
        self.assertEqual(_run_and_count("def f(): pass"), 1)

    def test_classdef(self):
        """ClassDef statement counts 1."""
        count = _run_and_count("class C: pass")
        # ClassDef(1) + Pass(1) inside class body = at least 2
        self.assertGreaterEqual(count, 2)

    def test_expr_statement_not_counted(self):
        """Expr statement wrapper is NOT counted (ops inside are)."""
        # 'len([])' is an Expr wrapping a Call + List — only Call + List count
        self.assertEqual(_run_and_count("len([])"), 2)

    def test_global_nonlocal_not_counted(self):
        """Global/Nonlocal are compile-time directives, not counted."""
        # FunctionDef(1) only
        self.assertEqual(_run_and_count("def f():\n    global x"), 1)


class ExpressionOperationCountTests(unittest.TestCase):
    """Test operation counts for expression operation AST nodes."""

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_call_single(self):
        """Single Call counts 1 + List(1) = 2."""
        self.assertEqual(_run_and_count("len([])"), 2)

    def test_call_nested(self):
        """Nested calls count independently."""
        self.assertEqual(_run_and_count("len(str(1))"), 2)

    def test_call_triple_nested(self):
        """Triple nested calls count 3."""
        self.assertEqual(_run_and_count("len(str(type(1)))"), 3)

    def test_binop_single(self):
        """Single BinOp counts 1."""
        # Assign(1) + BinOp(1) = 2
        self.assertEqual(_run_and_count("a = 1\nb = a + 1"), 3)  # Assign + Assign + BinOp

    def test_binop_chained(self):
        """Chained BinOps: a + b + c = 2 BinOp nodes."""
        # a=1 -> Assign(1), b=2 -> Assign(1), c=a+b+3 -> Assign(1)+BinOp(2) = 5
        self.assertEqual(_run_and_count("a = 1\nb = 2\nc = a + b + 3"), 5)

    def test_unaryop(self):
        """UnaryOp counts 1."""
        # Assign(1) + Assign(1) + UnaryOp(1) = 3
        self.assertEqual(_run_and_count("a = 1\nb = -a"), 3)

    def test_compare(self):
        """Compare counts 1."""
        # Assign(1) + Assign(1) + Compare(1) = 3
        self.assertEqual(_run_and_count("a = 1\nb = a < 2"), 3)

    def test_compare_chained(self):
        """Chained compare (a < b < c) is ONE Compare node."""
        # a=1 -> Assign(1), b=a<2<3 -> Assign(1)+Compare(1) = 3
        self.assertEqual(_run_and_count("a = 1\nb = 0 < a < 3"), 3)

    def test_boolop_and(self):
        """BoolOp 'and' counts 1."""
        self.assertEqual(_run_and_count("a = True\nb = a and True"), 3)

    def test_boolop_or(self):
        """BoolOp 'or' counts 1."""
        self.assertEqual(_run_and_count("a = False\nb = a or True"), 3)

    def test_attribute_load(self):
        """Attribute access (load) counts 1."""
        self.assertEqual(_run_and_count("a = []\na.append"), 3)  # Assign + List + Attr

    def test_subscript_load(self):
        """Subscript access (load) counts 1."""
        self.assertEqual(_run_and_count("a = [1]\nb = a[0]"), 4)  # Assign + List + Assign + Subscript


class CombinedCountTests(unittest.TestCase):
    """Test combined statement + expression operation counts."""

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_assign_with_call(self):
        """a = f(x) -> Assign(1) + Call(1) + List(1) = 3."""
        self.assertEqual(_run_and_count("a = len([])"), 3)

    def test_assign_with_call_and_binop(self):
        """a = f(x) + 1 -> Assign(1) + Call(1) + BinOp(1) + List(1) = 4."""
        self.assertEqual(_run_and_count("a = len([]) + 1"), 4)

    def test_return_with_call_and_binop(self):
        """return f(x) + 1 -> FunctionDef(1) + Call(outer)(1) + Return(1) + Call(len)(1) + BinOp(1) + List(1) = 6."""
        count = _run_and_count("def f():\n    return len([]) + 1\nf()")
        self.assertEqual(count, 6)

    def test_assert_with_compare(self):
        """assert a < b -> Assert(1) + Compare(1) = 2."""
        self.assertEqual(_run_and_count("a = 1\nassert a < 2"), 3)  # Assign + Assert + Compare

    def test_attribute_call(self):
        """obj.method() -> Assign(1) + List(1) + Attr(1) + Call(1) = 4."""
        self.assertEqual(_run_and_count("a = []\na.append(1)"), 4)  # Assign + List + Attr + Call

    def test_for_loop_body_per_iteration(self):
        """Loop body counted per iteration."""
        # For(1) + Call(range)(1) + Assign*3(3) = 5
        self.assertEqual(
            _run_and_count("for i in range(3):\n    a = i"), 5
        )

    def test_nested_for_loops(self):
        """Nested for loops multiply body counts."""
        # For(1) + Call(1) = 2 (outer)
        # (For(1) + Call(1)) * 3 = 6 (inner headers)
        # (Assign(1) + BinOp(1)) * 12 = 24 (inner body)
        # Total: 2 + 6 + 24 = 32
        count = _run_and_count(
            "for i in range(3):\n"
            "    for j in range(4):\n"
            "        x = i * j"
        )
        self.assertEqual(count, 32)


class OperationLimitTests(unittest.TestCase):
    """Test that operation limits are enforced."""

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_operation_limit_exceeded(self):
        """Exceeding scope_max_operations should raise SandboxRuntimeError."""
        sys.sandbox.set_limits(max_operations=3)
        sys.sandbox.add_filename(SANDBOX_FILENAME)
        sys.sandbox.reset_counts()

        # This should exceed the limit of 3
        source = "a = 1\nb = 2\nc = 3\nd = 4"  # 4 Assign ops
        code = _compile_sandboxed(source)
        with self.assertRaises(Exception) as ctx:
            exec(code, {"__builtins__": __builtins__})
        self.assertIn("operation limit", str(ctx.exception).lower())

    def test_operation_limit_not_exceeded(self):
        """Code within the operation limit should run normally."""
        sys.sandbox.set_limits(max_operations=10)
        sys.sandbox.add_filename(SANDBOX_FILENAME)
        sys.sandbox.reset_counts()

        source = "a = 1\nb = 2"  # 2 Assign ops
        code = _compile_sandboxed(source)
        exec(code, {"__builtins__": __builtins__})
        count = sys.sandbox.get_counts()["operation_count"]
        self.assertEqual(count, 2)

    def test_operations_counting_works(self):
        """Operation counting works correctly."""
        # Set operation limit
        sys.sandbox.set_limits(max_operations=100000)
        sys.sandbox.add_filename(SANDBOX_FILENAME)
        sys.sandbox.reset_counts()

        source = "a = 1\nb = 2\nc = 3"
        code = _compile_sandboxed(source)
        exec(code, {"__builtins__": __builtins__})
        counts = sys.sandbox.get_counts()
        # Operation count should reflect SANDBOX_COUNT opcodes
        self.assertEqual(counts["operation_count"], 3)

    def test_reset_clears_operation_count(self):
        """resetsandboxcounters should reset operation_count."""
        sys.sandbox.set_limits(max_operations=100000)
        sys.sandbox.add_filename(SANDBOX_FILENAME)

        # First exec
        sys.sandbox.reset_counts()
        code = _compile_sandboxed("a = 1")
        exec(code, {"__builtins__": __builtins__})
        self.assertEqual(sys.sandbox.get_counts()["operation_count"], 1)

        # Reset and exec again
        sys.sandbox.reset_counts()
        self.assertEqual(sys.sandbox.get_counts()["operation_count"], 0)
        exec(code, {"__builtins__": __builtins__})
        self.assertEqual(sys.sandbox.get_counts()["operation_count"], 1)


class CountIterationsAsOperationsTests(unittest.TestCase):
    """Test the count_iterations_as_operations flag."""

    ITER_FILENAME = "<sandbox-iter-ops-test>"

    def setUp(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.reset()

    def test_count_iterations_as_operations_default_off(self):
        """Flag defaults to 0; iterations don't increment operation_count."""
        limits = sys.sandbox.get_limits()
        self.assertIn("count_iterations_as_operations", limits)
        self.assertFalse(limits["count_iterations_as_operations"])

        # With flag off, iterating should not bump operation_count
        sys.sandbox.set_limits(max_iterations=1000, max_operations=1000)
        sys.sandbox.add_filename(self.ITER_FILENAME)
        sys.sandbox.reset_counts()

        code = compile("for _ in range(5): pass", self.ITER_FILENAME, "exec")
        exec(code, {"__builtins__": __builtins__})

        counts = sys.sandbox.get_counts()
        # Iterations happened but operation_count should be 0
        # (no SANDBOX_COUNT opcodes in the code)
        self.assertGreater(counts["iteration_count"], 0)
        self.assertEqual(counts["operation_count"], 0)

    def test_count_iterations_as_operations_enabled(self):
        """With flag on, each iteration yield also increments operation_count."""
        sys.sandbox.set_limits(
            max_iterations=1000,
            max_operations=1000,
            count_iterations_as_operations=True,
        )
        sys.sandbox.add_filename(self.ITER_FILENAME)
        sys.sandbox.reset_counts()

        code = compile("for _ in range(5): pass", self.ITER_FILENAME, "exec")
        exec(code, {"__builtins__": __builtins__})

        counts = sys.sandbox.get_counts()
        iter_count = counts["iteration_count"]
        op_count = counts["operation_count"]
        # Both should reflect the iteration yields
        self.assertGreater(iter_count, 0)
        self.assertEqual(op_count, iter_count)

    def test_count_iterations_as_operations_exceeds_limit(self):
        """Low max_operations + flag on -> SandboxRuntimeError from iterations."""
        sys.sandbox.set_limits(
            max_iterations=1000,
            max_operations=3,
            count_iterations_as_operations=True,
        )
        sys.sandbox.add_filename(self.ITER_FILENAME)
        sys.sandbox.reset_counts()

        # range(10) yields 10 items, should exceed max_operations=3
        code = compile("for _ in range(10): pass", self.ITER_FILENAME, "exec")
        with self.assertRaises(Exception) as ctx:
            exec(code, {"__builtins__": __builtins__})
        self.assertIn("operation limit", str(ctx.exception).lower())

    def test_count_iterations_as_operations_in_limits(self):
        """Flag appears in get_limits() dict."""
        sys.sandbox.set_limits(count_iterations_as_operations=True)
        limits = sys.sandbox.get_limits()
        self.assertTrue(limits["count_iterations_as_operations"])

        sys.sandbox.set_limits(count_iterations_as_operations=False)
        limits = sys.sandbox.get_limits()
        self.assertFalse(limits["count_iterations_as_operations"])


if __name__ == "__main__":
    unittest.main()

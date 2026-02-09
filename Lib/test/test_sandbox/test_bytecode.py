"""Bytecode-level tests for SANDBOX_COUNT opcode placement.

These tests compile source code and inspect the bytecode to verify that
SANDBOX_COUNT opcodes are properly placed by the compiler when using the
PyCF_SANDBOX_COUNT flag.  They complement the runtime-based tests in
test_operations.py: these tests never execute the compiled code.
"""

import dis
import unittest

PyCF_SANDBOX_COUNT = 0x8000
OPNAME = "SANDBOX_COUNT"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _compile_sandboxed(source, mode="exec"):
    """Compile *source* with the PyCF_SANDBOX_COUNT flag."""
    return compile(source, "<sandbox-bytecode-test>", mode,
                   flags=PyCF_SANDBOX_COUNT)


def _compile_normal(source, mode="exec"):
    """Compile *source* without the PyCF_SANDBOX_COUNT flag."""
    return compile(source, "<sandbox-bytecode-test>", mode)


def _count_sandbox_count(code_obj):
    """Return how many SANDBOX_COUNT instructions are in *code_obj*.

    Only inspects the given code object, not nested ones.
    """
    return sum(1 for instr in dis.get_instructions(code_obj)
               if instr.opname == OPNAME)


def _count_sandbox_count_recursive(code_obj):
    """Return the total SANDBOX_COUNT count in *code_obj* and all nested
    code objects found in ``co_consts``."""
    total = _count_sandbox_count(code_obj)
    for const in code_obj.co_consts:
        if hasattr(const, "co_code"):
            total += _count_sandbox_count_recursive(const)
    return total


def _has_sandbox_count(code_obj):
    """Return ``True`` if *code_obj* contains at least one SANDBOX_COUNT."""
    return _count_sandbox_count(code_obj) > 0


def _get_nested_code(code_obj, name=None):
    """Return the first nested code object, optionally filtered by
    ``co_name``.  Returns ``None`` if not found."""
    for const in code_obj.co_consts:
        if hasattr(const, "co_code"):
            if name is None or const.co_name == name:
                return const
    return None


# ===================================================================
# 1. Flag-controls-emission tests
# ===================================================================

class SandboxCountFlagTests(unittest.TestCase):
    """Verify that the PyCF_SANDBOX_COUNT flag controls emission."""

    def test_no_sandbox_count_without_flag_exec(self):
        """exec mode: no SANDBOX_COUNT without the flag."""
        code = _compile_normal("a = 1\nb = 2")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_no_sandbox_count_without_flag_eval(self):
        """eval mode: no SANDBOX_COUNT without the flag."""
        code = _compile_normal("a + b", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_sandbox_count_present_with_flag_exec(self):
        """exec mode: SANDBOX_COUNT present with the flag."""
        code = _compile_sandboxed("a = 1")
        self.assertTrue(_has_sandbox_count(code))

    def test_sandbox_count_present_with_flag_eval(self):
        """eval mode: SANDBOX_COUNT present for an expression that emits."""
        code = _compile_sandboxed("a + b", mode="eval")
        self.assertTrue(_has_sandbox_count(code))

    def test_nested_code_affected_by_flag(self):
        """Nested code objects should also contain SANDBOX_COUNT."""
        code = _compile_sandboxed("def f():\n    return 1")
        nested = _get_nested_code(code, "f")
        self.assertIsNotNone(nested)
        self.assertTrue(_has_sandbox_count(nested))

    def test_nested_code_no_flag(self):
        """Nested code without the flag should have no SANDBOX_COUNT."""
        code = _compile_normal("def f():\n    return 1")
        nested = _get_nested_code(code, "f")
        self.assertIsNotNone(nested)
        self.assertFalse(_has_sandbox_count(nested))

    def test_multiple_nested_all_affected(self):
        """All nested code objects should contain SANDBOX_COUNT."""
        code = _compile_sandboxed(
            "def f():\n    pass\ndef g():\n    pass"
        )
        for const in code.co_consts:
            if hasattr(const, "co_code"):
                self.assertTrue(
                    _has_sandbox_count(const),
                    f"nested code {const.co_name!r} missing SANDBOX_COUNT",
                )


# ===================================================================
# 2. Statement-level tests
# ===================================================================

class StatementSandboxCountTests(unittest.TestCase):
    """One test per statement type that should emit SANDBOX_COUNT."""

    def test_assign(self):
        """Assign: ``a = 1`` -> 1."""
        code = _compile_sandboxed("a = 1")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_multiple_assigns(self):
        """Three assigns -> 3."""
        code = _compile_sandboxed("a = 1\nb = 2\nc = 3")
        self.assertEqual(_count_sandbox_count(code), 3)

    def test_augassign(self):
        """AugAssign: ``a = 0; a += 1`` -> 2."""
        code = _compile_sandboxed("a = 0\na += 1")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_annassign(self):
        """AnnAssign: ``a: int = 1`` -> 1."""
        code = _compile_sandboxed("a: int = 1")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_delete(self):
        """Delete: ``a = 1; del a`` -> 2."""
        code = _compile_sandboxed("a = 1\ndel a")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_pass(self):
        """Pass: ``pass`` -> 1."""
        code = _compile_sandboxed("pass")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_if(self):
        """If: ``if True: pass`` -> 2 (If + Pass)."""
        code = _compile_sandboxed("if True:\n    pass")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_for(self):
        """For: ``for x in y: pass`` -> 2 (For + Pass)."""
        code = _compile_sandboxed("for x in y:\n    pass")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_while_body_entered(self):
        """While: ``while True: break`` -> 2 (While + Break)."""
        code = _compile_sandboxed("while True:\n    break")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_while_body_not_entered(self):
        """While: ``while False: pass`` -> 1 (While only, body not reached
        but the SANDBOX_COUNT for the body pass is still in bytecode)."""
        code = _compile_sandboxed("while False:\n    pass")
        # The compiler may optimise away the unreachable body; we just
        # check the While node itself emits at least 1.
        self.assertGreaterEqual(_count_sandbox_count(code), 1)

    def test_return(self):
        """Return: in nested code -> 1."""
        code = _compile_sandboxed("def f():\n    return 1")
        nested = _get_nested_code(code, "f")
        self.assertEqual(_count_sandbox_count(nested), 1)

    def test_functiondef_top_level(self):
        """FunctionDef: ``def f(): pass`` -> 1 at top level."""
        code = _compile_sandboxed("def f():\n    pass")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_functiondef_body(self):
        """FunctionDef body: the Pass inside the body -> 1 in nested."""
        code = _compile_sandboxed("def f():\n    pass")
        nested = _get_nested_code(code, "f")
        self.assertEqual(_count_sandbox_count(nested), 1)

    def test_classdef(self):
        """ClassDef: ``class C: pass`` -> 1 top-level (the ClassDef stmt)
        plus the class body code object also gets counts."""
        code = _compile_sandboxed("class C:\n    pass")
        # At least the ClassDef statement itself
        self.assertGreaterEqual(_count_sandbox_count(code), 1)

    def test_classdef_body(self):
        """ClassDef body: the Pass inside ``class C: pass`` -> 1."""
        code = _compile_sandboxed("class C:\n    pass")
        nested = _get_nested_code(code, "C")
        self.assertIsNotNone(nested)
        self.assertEqual(_count_sandbox_count(nested), 1)

    def test_raise(self):
        """Raise: ``raise Exception`` -> 1."""
        code = _compile_sandboxed("raise Exception")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_try_except(self):
        """Try/except: ``try: pass except: pass`` -> 3 (Try + Pass + Pass)."""
        code = _compile_sandboxed("try:\n    pass\nexcept:\n    pass")
        self.assertEqual(_count_sandbox_count(code), 3)

    def test_assert(self):
        """Assert: ``assert True`` -> 1."""
        code = _compile_sandboxed("assert True")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_import(self):
        """Import: ``import sys`` -> 1."""
        code = _compile_sandboxed("import sys")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_import_from(self):
        """ImportFrom: ``from sys import path`` -> 1."""
        code = _compile_sandboxed("from sys import path")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_break(self):
        """Break: ``for x in y: break`` -> 2 (For + Break)."""
        code = _compile_sandboxed("for x in y:\n    break")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_continue(self):
        """Continue: ``for x in y: continue`` -> 2 (For + Continue)."""
        code = _compile_sandboxed("for x in y:\n    continue")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_match(self):
        """Match: ``match x: case 1: pass`` -> >= 2."""
        code = _compile_sandboxed("match x:\n    case 1:\n        pass")
        self.assertGreaterEqual(_count_sandbox_count(code), 2)

    def test_with(self):
        """With: ``with x: pass`` -> 2 (With + Pass)."""
        code = _compile_sandboxed("with x:\n    pass")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_async_functiondef(self):
        """AsyncFunctionDef: top-level -> 1."""
        code = _compile_sandboxed("async def f():\n    pass")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_async_functiondef_body(self):
        """AsyncFunctionDef body -> 1 (Pass) in nested code."""
        code = _compile_sandboxed("async def f():\n    pass")
        nested = _get_nested_code(code, "f")
        self.assertIsNotNone(nested)
        self.assertEqual(_count_sandbox_count(nested), 1)

    def test_async_for(self):
        """AsyncFor: in nested code -> 2 (AsyncFor + Pass)."""
        code = _compile_sandboxed(
            "async def f():\n    async for x in y:\n        pass"
        )
        nested = _get_nested_code(code, "f")
        self.assertIsNotNone(nested)
        self.assertEqual(_count_sandbox_count(nested), 2)

    def test_async_with(self):
        """AsyncWith: in nested code -> 2 (AsyncWith + Pass)."""
        code = _compile_sandboxed(
            "async def f():\n    async with x:\n        pass"
        )
        nested = _get_nested_code(code, "f")
        self.assertIsNotNone(nested)
        self.assertEqual(_count_sandbox_count(nested), 2)


# ===================================================================
# 3. Statements that should NOT emit
# ===================================================================

class StatementNoSandboxCountTests(unittest.TestCase):
    """Verify compile-time directives do NOT emit SANDBOX_COUNT."""

    def test_global_not_counted(self):
        """Global is a compile-time directive, not counted."""
        code = _compile_sandboxed("def f():\n    global x")
        nested = _get_nested_code(code, "f")
        self.assertEqual(_count_sandbox_count(nested), 0)

    def test_nonlocal_not_counted(self):
        """Nonlocal is a compile-time directive, not counted."""
        code = _compile_sandboxed(
            "def outer():\n"
            "    x = 1\n"
            "    def inner():\n"
            "        nonlocal x\n"
        )
        outer = _get_nested_code(code, "outer")
        inner = _get_nested_code(outer, "inner")
        self.assertIsNotNone(inner)
        self.assertEqual(_count_sandbox_count(inner), 0)

    def test_expr_wrapper_not_counted(self):
        """Expr statement wrapper does not add its own SANDBOX_COUNT;
        the inner expression (e.g. a Call) and container constructions emit."""
        code = _compile_sandboxed("len([])")
        # The Call and the list construction each emit SANDBOX_COUNT
        self.assertEqual(_count_sandbox_count(code), 2)


# ===================================================================
# 4. Expression-level tests
# ===================================================================

class ExpressionSandboxCountTests(unittest.TestCase):
    """Test SANDBOX_COUNT for expression nodes (eval mode for clean counts)."""

    def test_binop(self):
        """BinOp: ``a + b`` -> 1."""
        code = _compile_sandboxed("a + b", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_binop_chained(self):
        """Chained BinOps: ``a + b + c`` -> 2 (two BinOp AST nodes)."""
        code = _compile_sandboxed("a + b + c", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_boolop(self):
        """BoolOp: ``a and b`` -> 1."""
        code = _compile_sandboxed("a and b", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_unaryop(self):
        """UnaryOp: ``-a`` -> 1."""
        code = _compile_sandboxed("-a", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_compare(self):
        """Compare: ``a < b`` -> 1."""
        code = _compile_sandboxed("a < b", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_compare_chained(self):
        """Chained compare: ``a < b < c`` is one Compare AST node -> 1."""
        code = _compile_sandboxed("a < b < c", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_attribute(self):
        """Attribute: ``a.b`` -> 1."""
        code = _compile_sandboxed("a.b", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_subscript(self):
        """Subscript: ``a[0]`` -> 1."""
        code = _compile_sandboxed("a[0]", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_list(self):
        """List: ``[1, 2]`` -> 1 (container construction is counted)."""
        code = _compile_sandboxed("[1, 2]", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_dict(self):
        """Dict: ``{1: 2}`` -> 1 (container construction is counted)."""
        code = _compile_sandboxed("{1: 2}", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_set(self):
        """Set: ``{1, 2}`` -> 1 (container construction is counted)."""
        code = _compile_sandboxed("{1, 2}", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_lambda(self):
        """Lambda: ``lambda: 1`` -> 1 (creates a function object,
        consistent with FunctionDef)."""
        code = _compile_sandboxed("lambda: 1", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_listcomp(self):
        """ListComp: ``[x for x in a]`` -> 1 (creates a list object)."""
        code = _compile_sandboxed("[x for x in a]", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_setcomp(self):
        """SetComp: ``{x for x in a}`` -> 1 (creates a set object)."""
        code = _compile_sandboxed("{x for x in a}", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_dictcomp(self):
        """DictComp: ``{x: x for x in a}`` -> 1 (creates a dict object)."""
        code = _compile_sandboxed("{x: x for x in a}", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_generatorexp(self):
        """GeneratorExp: ``(x for x in a)`` -> 1 (creates a generator object)."""
        code = _compile_sandboxed("(x for x in a)", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_slice(self):
        """Slice: ``a[1:2]`` -> 2 (1 for Subscript + 1 for Slice)."""
        code = _compile_sandboxed("a[1:2]", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)


# ===================================================================
# 5. Expressions that should NOT emit
# ===================================================================

class ExpressionNoSandboxCountTests(unittest.TestCase):
    """Verify these expression forms do NOT emit SANDBOX_COUNT."""

    def test_constant(self):
        """Constant: ``42`` -> 0."""
        code = _compile_sandboxed("42", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_name(self):
        """Name: ``a`` -> 0."""
        code = _compile_sandboxed("a", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_tuple(self):
        """Tuple: ``(1, 2)`` -> 0 (constant tuple is folded)."""
        code = _compile_sandboxed("(1, 2)", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_namedexpr(self):
        """NamedExpr: ``(x := 1)`` -> 0."""
        code = _compile_sandboxed("(x := 1)", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_ifexp(self):
        """IfExp: ``1 if True else 2`` -> 0."""
        code = _compile_sandboxed("1 if True else 2", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)

    def test_fstring(self):
        """f-string: ``f'{1}'`` -> 0."""
        code = _compile_sandboxed("f'{1}'", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 0)


# ===================================================================
# 6. Call-related tests
# ===================================================================

class CallSandboxCountTests(unittest.TestCase):
    """Test SANDBOX_COUNT placement around calls."""

    def test_simple_call(self):
        """Simple call: ``f()`` -> 1."""
        code = _compile_sandboxed("f()", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_method_call(self):
        """Method call: ``a.b()`` -> 2 (Attribute + Call)."""
        code = _compile_sandboxed("a.b()", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_nested_calls(self):
        """Nested calls: ``f(g())`` -> 2."""
        code = _compile_sandboxed("f(g())", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_star_call(self):
        """Star call: ``f(*args)`` -> 1."""
        code = _compile_sandboxed("f(*args)", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_kwargs_call(self):
        """Kwargs call: ``f(**kw)`` -> 1."""
        code = _compile_sandboxed("f(**kw)", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 1)

    def test_chained_method_call(self):
        """Chained method: ``a.b().c()`` -> 4 (Attr + Call + Attr + Call)."""
        code = _compile_sandboxed("a.b().c()", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 4)

    def test_decorator(self):
        """Decorator: ``@dec def f(): pass`` -> 2 top-level
        (FunctionDef + decorator call)."""
        code = _compile_sandboxed("@dec\ndef f():\n    pass")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_multiple_decorators(self):
        """Multiple decorators: ``@d1 @d2 @d3 def f(): pass`` -> 4
        (FunctionDef + 3 decorator calls)."""
        code = _compile_sandboxed(
            "@d1\n@d2\n@d3\ndef f():\n    pass"
        )
        self.assertEqual(_count_sandbox_count(code), 4)

    def test_triple_nested_calls(self):
        """Triple nested: ``f(g(h()))`` -> 3."""
        code = _compile_sandboxed("f(g(h()))", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 3)


# ===================================================================
# 7. Combined / multi-node pattern tests
# ===================================================================

class CombinedBytecodeSandboxCountTests(unittest.TestCase):
    """Exact totals for multi-node patterns."""

    def test_assign_with_constant_binop(self):
        """``a = 1 + 2`` -> 2 (Assign + BinOp; BinOp counted even if constant-folded)."""
        code = _compile_sandboxed("a = 1 + 2")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_assign_with_call(self):
        """``a = f()`` -> 2 (Assign + Call)."""
        code = _compile_sandboxed("a = f()")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_if_with_compare_and_pass(self):
        """``if a < b: pass`` -> 3 (If + Compare + Pass)."""
        code = _compile_sandboxed("if a < b:\n    pass")
        self.assertEqual(_count_sandbox_count(code), 3)

    def test_for_with_call_and_body(self):
        """``for x in range(10): a = x + 1`` -> 4
        (For + Call(range) + Assign + BinOp)."""
        code = _compile_sandboxed("for x in range(10):\n    a = x + 1")
        self.assertEqual(_count_sandbox_count(code), 4)

    def test_function_with_body_recursive(self):
        """``def f(): return 1 + 2`` -> 2 total
        (1 FunctionDef top-level + 1 Return in nested; BinOp folded)."""
        code = _compile_sandboxed("def f():\n    return 1 + 2")
        self.assertEqual(_count_sandbox_count_recursive(code), 2)

    def test_triple_nested_calls_eval(self):
        """``f(g(h()))`` eval -> 3."""
        code = _compile_sandboxed("f(g(h()))", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 3)

    def test_chained_attribute(self):
        """``a.b.c`` eval -> 2 (two Attribute nodes)."""
        code = _compile_sandboxed("a.b.c", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)

    def test_attribute_then_subscript(self):
        """``a.b[0]`` eval -> 2 (Attribute + Subscript)."""
        code = _compile_sandboxed("a.b[0]", mode="eval")
        self.assertEqual(_count_sandbox_count(code), 2)


if __name__ == "__main__":
    unittest.main()

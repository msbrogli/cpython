- Feature Name: sandbox-operations
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox operations module provides precise AST-level operation counting through a dedicated `SANDBOX_COUNT` opcode. Unlike statement counting (which uses line tracing), operation counting is compiler-based and deterministic: the compiler emits `SANDBOX_COUNT` opcodes at specific AST nodes, and each opcode execution increments the operation counter.

# Motivation
[motivation]: #motivation

Statement counting has limitations:

1. **Non-deterministic**: Count depends on bytecode layout, not source structure
2. **Tracing overhead**: Line tracing impacts all code, not just sandboxed code
3. **Granularity**: Counts lines, not semantic operations

Operation counting solves these issues:

1. **Deterministic**: Same source always produces same operation count
2. **Opt-in overhead**: Only code compiled with flag has the opcodes
3. **Semantic**: Counts actual operations (calls, arithmetic, attribute access)

This enables precise cost accounting for untrusted code execution.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Compiling with Operation Counting

Use the `PyCF_SANDBOX_COUNT` flag when compiling:

```python
import sys

# Enable operation limit
sys.sandbox.max_operations = 10000
sys.sandbox.add_filename("<sandbox>")

# Compile with SANDBOX_COUNT opcodes
PyCF_SANDBOX_COUNT = 0x8000
code = compile(source, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

# Reset counter before execution
sys.sandbox.reset_counts()

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Sandbox operation limit exceeded"
```

## What Gets Counted?

Operations are counted at the AST level:

### Counted Statements
- `Assign` (x = y)
- `AugAssign` (x += y)
- `Delete` (del x)
- `Pass`
- `Break`
- `Continue`
- `Return`
- `If`
- `For`
- `While`
- `Try`
- `Import`
- `ImportFrom`
- `Assert`
- `FunctionDef`
- `ClassDef`

### Counted Expressions
- `Call` (func())
- `BinOp` (a + b)
- `UnaryOp` (-x)
- `Compare` (a < b)
- `BoolOp` (a and b)
- `Attribute` (obj.attr)
- `Subscript` (obj[key])

### NOT Counted
- `Expr` (statement wrapper - avoids double counting)
- `Global`, `Nonlocal` (compile-time directives)
- `Name` loads (x)
- Literal values (1, "hello", [])

## Example: Counting Operations

```python
# Source code:
x = 1 + 2       # 2 ops: Assign + BinOp
y = x * 3       # 2 ops: Assign + BinOp
if y > 5:       # 2 ops: If + Compare
    print(y)    # 1 op: Call
# Total: 7 operations

sys.sandbox.max_operations = 100
code = compile(source, "<sandbox>", "exec", flags=0x8000)
exec(code)
print(sys.sandbox.operation_count)  # 7
```

## Counting Iterations as Operations

You can merge iteration counting into operation counting:

```python
sys.sandbox.set_limits(
    max_operations=100000,
    count_iterations_as_operations=True,
)

# Now both SANDBOX_COUNT opcodes AND iterator yields
# increment operation_count
```

This provides a unified "cost" budget.

## Zero Overhead When Disabled

Code compiled **without** `PyCF_SANDBOX_COUNT` has no `SANDBOX_COUNT` opcodes, so there's zero runtime overhead:

```python
# Normal compilation - no overhead
normal_code = compile(source, "normal.py", "exec")

# Sandbox compilation - has SANDBOX_COUNT opcodes
sandbox_code = compile(source, "<sandbox>", "exec", flags=0x8000)
```

## Inspecting the Bytecode

```python
import dis

source = "x = 1 + 2"
code = compile(source, "<sandbox>", "exec", flags=0x8000)

dis.dis(code)
# Output includes SANDBOX_COUNT opcodes:
#   0 SANDBOX_COUNT
#   2 LOAD_CONST        0 (1)
#   4 SANDBOX_COUNT
#   6 LOAD_CONST        1 (2)
#   8 BINARY_ADD
#  10 STORE_NAME        0 (x)
#  ...
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Compile Flag

Defined in `Include/cpython/compile.h`:

```c
#define PyCF_SANDBOX_COUNT 0x8000
```

Added to `PyCF_MASK`:

```c
#define PyCF_MASK (PyCF_SOURCE_IS_UTF8 | PyCF_DONT_IMPLY_DEDENT | \
                   PyCF_ONLY_AST | PyCF_IGNORE_COOKIE | \
                   PyCF_TYPE_COMMENTS | PyCF_ALLOW_TOP_LEVEL_AWAIT | \
                   PyCF_ALLOW_INCOMPLETE_INPUT | PyCF_SANDBOX_COUNT)
```

## Opcode Definition

In `Include/opcode.h` and `Lib/opcode.py`:

```c
#define SANDBOX_COUNT  181
```

The opcode takes no arguments and has no stack effect.

## Compiler Integration

In `Python/compile.c`, a macro emits the opcode conditionally:

```c
#define ADDOP_SANDBOX_COUNT(C) { \
    if ((C)->c_flags->cf_flags & PyCF_SANDBOX_COUNT) { \
        ADDOP((C), SANDBOX_COUNT); \
    } \
}
```

This macro is placed at the start of AST node visitor functions:

```c
static int
compiler_visit_stmt(struct compiler *c, stmt_ty s)
{
    switch (s->kind) {
    case Assign_kind:
        ADDOP_SANDBOX_COUNT(c);
        /* ... compile assignment ... */
        break;

    case If_kind:
        ADDOP_SANDBOX_COUNT(c);
        /* ... compile if statement ... */
        break;

    /* ... other statement types ... */
    }
    return 1;
}

static int
compiler_visit_expr(struct compiler *c, expr_ty e)
{
    switch (e->kind) {
    case Call_kind:
        ADDOP_SANDBOX_COUNT(c);
        /* ... compile call ... */
        break;

    case BinOp_kind:
        ADDOP_SANDBOX_COUNT(c);
        /* ... compile binary operation ... */
        break;

    /* ... other expression types ... */
    }
    return 1;
}
```

## Runtime Handler

In `Python/ceval.c`:

```c
TARGET(SANDBOX_COUNT) {
    PyInterpreterState *interp = tstate->interp;
    if (interp->sandbox.limits.max_operations > 0 &&
        !interp->sandbox.suspended) {
        if (_PySandbox_CheckScopeOperation() < 0) {
            goto error;
        }
    }
    DISPATCH();
}
```

## Check Function

In `Python/sandbox_limits.c`:

```c
int
_PySandbox_CheckScopeOperation(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;
    _PySandboxCounters *counters = &sandbox->counters;

    if (limits->max_operations == 0 ||
        sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    /* Check if in sandbox scope */
    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    counters->operation_count++;

    /* Single-raise: only at exactly max+1 */
    if (counters->operation_count == limits->max_operations + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}
```

## C API

```c
/* Check operation limit (called from SANDBOX_COUNT handler) */
int _PySandbox_CheckScopeOperation(void);
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `max_operations` | int | 0 | Max operation count (0 = no limit) |
| `operation_count` | int (read-only) | 0 | Current operation count |
| `count_iterations_as_operations` | bool | False | Count iterations as operations |

### Compile Flag

```python
PyCF_SANDBOX_COUNT = 0x8000

code = compile(source, filename, mode, flags=PyCF_SANDBOX_COUNT)
```

## Performance Analysis

### Without `PyCF_SANDBOX_COUNT`

No `SANDBOX_COUNT` opcodes in bytecode = **zero runtime overhead**.

### With `PyCF_SANDBOX_COUNT` but `max_operations == 0`

Each `SANDBOX_COUNT` opcode:
1. Load interpreter state (1 memory read)
2. Check `max_operations == 0` (1 comparison)
3. Return 0

Cost: ~2-3 CPU cycles per counted operation.

### With `PyCF_SANDBOX_COUNT` and `max_operations > 0`

Each `SANDBOX_COUNT` opcode:
1. Load sandbox state
2. Check suspended flag
3. Scope check (set lookup)
4. Increment counter
5. Compare against limit

Cost: ~10-20 CPU cycles per counted operation.

## Determinism

Operation counting is deterministic because:

1. **Compiler-based**: Same source → same opcodes → same count
2. **AST-level**: Counts semantic operations, not bytecode details
3. **Version-independent**: AST structure is stable across minor versions

Compare to statement counting:
## Determinism

Operation counting is deterministic:

| Aspect | Description |
|--------|-------------|
| Counter | `operation_count` |
| Limit | `max_operations` |
| Mechanism | Compiler-emitted `SANDBOX_COUNT` opcode |
| Determinism | **Yes** - same source always produces same count |
| Overhead | Only in code compiled with `PyCF_SANDBOX_COUNT` flag |

# Drawbacks
[drawbacks]: #drawbacks

1. **Compilation Required**: Must compile with special flag; can't retrofit existing `.pyc` files.

2. **Bytecode Size**: `SANDBOX_COUNT` opcodes increase bytecode size (~10-20%).

3. **Learning Curve**: Users must understand what operations are counted.

4. **Version Coupling**: Opcode number (181) could conflict with future Python opcodes.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Dedicated Opcode vs. Tracing?

**Alternative**: Use `sys.settrace()` with operation-level granularity.

- Rejected: Tracing has significant overhead; applies to all code, not just sandboxed code; non-deterministic.

**Alternative**: Count opcodes directly in ceval.c.

- Rejected: Would require modifying every opcode handler; no way to opt-out.

**Chosen**: Dedicated opcode provides opt-in, low-overhead counting.

## Why Compiler Flag vs. Decorator?

**Alternative**: `@sandbox_count` decorator.

- Rejected: Can't modify bytecode post-compilation; would need runtime wrapper.

**Alternative**: Runtime flag that enables counting for all code.

- Rejected: No way to have some code counted and some not.

**Chosen**: Compile flag gives precise control over what code is counted.

## Why Not Count All Opcodes?

Counting every opcode would:
- Have much higher overhead
- Not map to semantic operations users understand
- Count internal implementation details

Counting AST operations is more meaningful and predictable.

# Prior art
[prior-art]: #prior-art

1. **Gas Metering (Ethereum)**: Each EVM opcode has a "gas cost". Similar concept of operation-level cost accounting.

2. **CPU Cycle Counting**: Hardware performance counters. Lower-level than operation counting.

3. **Coverage.py**: Uses similar compile-time instrumentation for code coverage.

4. **Python's `sys.settrace()`**: Similar concept but runtime-based rather than compile-time.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be configurable weights for different operation types?

2. Should loop iterations be counted separately from loop entry?

3. Should comprehensions be counted as single operations or expanded?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Operation Weights**: Configure cost per operation type (e.g., `Call` costs 10, `BinOp` costs 1).

2. **Operation Profiling**: Track which operations consume the most budget.

3. **JIT Integration**: Count operations in JIT-compiled code.

4. **Async Operation Counting**: Handle `await` and async operations specially.

5. **Memory Operation Counting**: Count memory-intensive operations separately.

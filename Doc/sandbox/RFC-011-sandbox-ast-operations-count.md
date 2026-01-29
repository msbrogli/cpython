- Feature Name: sandbox-ast-operations-count
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

This RFC describes an improved implementation of sandbox operation counting that moves the counting logic from hardcoded compiler calls to AST node attributes. Each AST node has an `operations_count` attribute that is set during parsing (for nodes that should count) and accumulated during AST optimization (for folded constants). The compiler emits `SANDBOX_COUNT N` opcodes based on this attribute, providing a single unified emission point.

# Motivation
[motivation]: #motivation

The previous implementation of operation counting had several issues:

1. **Scattered emission**: ~37 hardcoded `ADDOP_SANDBOX_COUNT(c)` calls spread throughout `compile.c`
2. **Inconsistent**: Difficult to understand which nodes were counted and why
3. **Hard to modify**: Changing what counts required editing `compile.c` in many places
4. **No folding support**: Constant folding didn't properly accumulate operation counts

The new AST-based approach solves these issues by:

1. **Centralized logic**: Single check in compiler visitor functions
2. **Explicit**: The `operations_count` attribute clearly indicates what gets counted
3. **Easy to modify**: Change counting by updating grammar rules (EXTRA vs EXTRA_OP1)
4. **Folding-aware**: AST optimizer accumulates counts when folding expressions

This enables deterministic, maintainable, and accurate cost accounting for sandboxed code.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## How It Works

Every AST node has an `operations_count` attribute:

```
# In Parser/Python.asdl
stmt = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

expr = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)
```

During parsing:
- Nodes that should count get `operations_count = 1` (via `EXTRA_OP1` macro)
- Nodes that shouldn't count get `operations_count = 0` (via `EXTRA` macro)

During AST optimization (constant folding):
- Folded operations accumulate their counts into the result

During compilation:
- The compiler checks `node->operations_count` and emits `SANDBOX_COUNT N` if > 0

## Example 1: Simple Binary Operation

```python
# Source: a + b
# Parsed as: BinOp(left=Name('a'), op=Add(), right=Name('b'))
#   - BinOp gets operations_count=1 (via EXTRA_OP1 in grammar)
#   - Name nodes get operations_count=0 (variable loads are cheap)
```

Bytecode (with SANDBOX_COUNT flag):
```
SANDBOX_COUNT    1      # From BinOp.operations_count
LOAD_NAME        a
LOAD_NAME        b
BINARY_OP        +
```

## Example 2: Constant Folding

```python
# Source: (1 + 2) * (3 + 4)
# Before optimization:
#   BinOp(                        # operations_count=1
#     left=BinOp(                 # operations_count=1
#       left=Constant(1),         # operations_count=0
#       right=Constant(2)),       # operations_count=0
#     right=BinOp(                # operations_count=1
#       left=Constant(3),         # operations_count=0
#       right=Constant(4)))       # operations_count=0
#
# After optimization:
#   Constant(21, operations_count=3)  # Accumulated: 1+1+1=3
```

Bytecode:
```
SANDBOX_COUNT    3      # From folded Constant.operations_count
LOAD_CONST       21
```

## Example 3: Statements

```python
# Source: if x > 0: pass
# Parsed as:
#   If(                           # operations_count=1
#     test=Compare(               # operations_count=1
#       left=Name('x'),           # operations_count=0
#       ops=[Gt()],
#       comparators=[Constant(0)] # operations_count=0
#     ),
#     body=[Pass()]               # operations_count=1
#   )
```

Bytecode:
```
SANDBOX_COUNT    1      # From If.operations_count
SANDBOX_COUNT    1      # From Compare.operations_count
LOAD_NAME        x
LOAD_CONST       0
COMPARE_OP       >
POP_JUMP_IF_FALSE ...
SANDBOX_COUNT    1      # From Pass.operations_count
JUMP_FORWARD     ...
```

## Example 4: Non-counting Nodes

Some nodes don't count as operations:

```python
# Source: global x
# Parsed as: Global(names=['x'], operations_count=0)
#
# No SANDBOX_COUNT emitted - global is a compile-time directive
```

```python
# Source: 42
# Parsed as: Constant(42, operations_count=0)
#
# No SANDBOX_COUNT emitted - literals are free
```

```python
# Source: x
# Parsed as: Name('x', operations_count=0)
#
# No SANDBOX_COUNT emitted - variable loads are cheap
```

## What Gets Counted

### Statements with `operations_count=1` (EXTRA_OP1)

| Statement | Why It Counts |
|-----------|---------------|
| FunctionDef, AsyncFunctionDef | Definition creates a function object |
| ClassDef | Definition creates a class object |
| Return | Control flow operation |
| Delete | Memory mutation |
| Assign, AugAssign, AnnAssign | Memory mutation |
| For, AsyncFor | Loop setup |
| While | Loop setup |
| If | Branch evaluation |
| With, AsyncWith | Context management |
| Match | Pattern matching evaluation |
| Raise | Exception creation |
| Try, TryStar | Exception handling setup |
| Assert | Runtime assertion check |
| Import, ImportFrom | Module loading |
| Pass | Execution step (prevents infinite loops) |
| Break, Continue | Control flow operation |

### Statements with `operations_count=0` (EXTRA)

| Statement | Why It Doesn't Count |
|-----------|---------------------|
| Global | Compile-time directive, no runtime effect |
| Nonlocal | Compile-time directive, no runtime effect |
| Expr | Wrapper statement, delegates to inner expression |

### Expressions with `operations_count=1` (EXTRA_OP1)

| Expression | Why It Counts |
|------------|---------------|
| BoolOp | Logical operation evaluation |
| BinOp | Arithmetic/bitwise computation |
| UnaryOp | Negation/inversion computation |
| Compare | Comparison evaluation |
| Call | Function invocation |
| Attribute | Attribute lookup |
| Subscript | Index lookup |
| Dict, Set, List, Tuple | Container construction |

### Expressions with `operations_count=0` (EXTRA)

| Expression | Why It Doesn't Count |
|------------|---------------------|
| Constant | Literal value, no computation |
| Name | Variable lookup is cheap |
| Lambda | Definition only, no invocation |
| IfExp | Branches are handled separately |
| Comprehensions | Iteration is handled by iterator limits |
| Yield, YieldFrom, Await | Generator/async protocol |
| Starred, Slice | Syntax constructs |
| NamedExpr | Assignment target handles counting |
| FormattedValue, JoinedStr | String parts counted individually |

## Constant Folding Accumulation

The AST optimizer (`ast_opt.c`) accumulates operation counts when folding:

```c
// In fold_binop:
// newval = lhs OP rhs
// newval.operations_count = 1 + lhs.operations_count + rhs.operations_count
```

Examples of folding:

| Expression | Folded To | operations_count |
|------------|-----------|------------------|
| `1 + 2` | `3` | 1 (one BinOp) |
| `(1 + 2) * 3` | `9` | 2 (two BinOps) |
| `(1 + 2) * (3 + 4)` | `21` | 3 (three BinOps) |
| `-(-5)` | `5` | 2 (two UnaryOps) |
| `not not True` | `True` | 2 (two UnaryOps) |

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## AST Definition Changes

In `Parser/Python.asdl`, the `operations_count` attribute is added to all node types that have attributes:

```asdl
stmt = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

expr = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

excepthandler = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

arg = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

keyword = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

alias = ...
    attributes (int lineno, int col_offset, int? end_lineno, int? end_col_offset, int? operations_count)

pattern = ...
    attributes (int lineno, int col_offset, int end_lineno, int end_col_offset, int? operations_count)
```

The `int?` makes it optional, allowing Python's `ast` module to create nodes without specifying this internal attribute.

## Parser Macros

In `Parser/pegen.h`:

```c
/* EXTRA passes operations_count=0 by default. The operations_count
 * will be accumulated during AST optimization when folding occurs. */
#define EXTRA_EXPR(head, tail) head->lineno, (head)->col_offset, (tail)->end_lineno, (tail)->end_col_offset, 0, p->arena
#define EXTRA _start_lineno, _start_col_offset, _end_lineno, _end_col_offset, 0, p->arena

/* EXTRA_OP1 passes operations_count=1 for nodes that should count as operations */
#define EXTRA_OP1 _start_lineno, _start_col_offset, _end_lineno, _end_col_offset, 1, p->arena
```

## Grammar Rules

In `Grammar/python.gram`, rules use `EXTRA_OP1` for counting nodes:

```python
# Statements
pass_stmt[stmt_ty]: 'pass' { _PyAST_Pass(EXTRA_OP1) }
break_stmt[stmt_ty]: 'break' { _PyAST_Break(EXTRA_OP1) }
continue_stmt[stmt_ty]: 'continue' { _PyAST_Continue(EXTRA_OP1) }

# Expressions
sum[expr_ty]:
    | a=sum '+' b=term { _PyAST_BinOp(a, Add, b, EXTRA_OP1) }
    | a=sum '-' b=term { _PyAST_BinOp(a, Sub, b, EXTRA_OP1) }
    | term

# Non-counting (uses EXTRA)
global_stmt[stmt_ty]: 'global' a=','.NAME+ { _PyAST_Global(..., EXTRA) }
```

## Compiler Changes

In `Python/compile.c`, the emission is unified:

```c
static int
compiler_visit_stmt(struct compiler *c, stmt_ty s)
{
    SET_LOC(c, s);

    /* Unified operation counting - emit if this node should count */
    ADDOP_SANDBOX_COUNT_N(c, s->operations_count);

    switch (s->kind) {
    case FunctionDef_kind:
        return compiler_function(c, s, 0);
    case If_kind:
        return compiler_if(c, s);
    /* ... other cases without individual ADDOP_SANDBOX_COUNT calls ... */
    }
}

static int
compiler_visit_expr1(struct compiler *c, expr_ty e)
{
    /* Unified operation counting - emit if this node should count */
    ADDOP_SANDBOX_COUNT_N(c, e->operations_count);

    switch (e->kind) {
    case BinOp_kind:
        /* ... compile binary operation ... */
    case Call_kind:
        /* ... compile call ... */
    /* ... other cases ... */
    }
}
```

The `ADDOP_SANDBOX_COUNT_N` macro:

```c
#define ADDOP_SANDBOX_COUNT_N(C, N) { \
    if ((C)->c_flags->cf_flags & PyCF_SANDBOX_COUNT && (N) > 0) { \
        ADDOP_I((C), SANDBOX_COUNT, (N)); \
    } \
}
```

## AST Optimization

In `Python/ast_opt.c`, folding functions accumulate counts:

```c
static int
fold_binop(expr_ty node, PyArena *arena, _PyASTOptimizeState *state)
{
    expr_ty lhs = node->v.BinOp.left;
    expr_ty rhs = node->v.BinOp.right;

    /* ... compute folded value ... */

    /* Accumulate operation counts:
     * The folded constant inherits the counts from both operands
     * plus the current operation (1 for this BinOp) */
    int accumulated_count = 1 + lhs->operations_count + rhs->operations_count;

    return make_const(node, newval, arena, accumulated_count);
}

static int
fold_unaryop(expr_ty node, PyArena *arena, _PyASTOptimizeState *state)
{
    expr_ty arg = node->v.UnaryOp.operand;

    /* ... compute folded value ... */

    /* Accumulate: 1 for this UnaryOp + arg's count */
    int accumulated_count = 1 + arg->operations_count;

    return make_const(node, newval, arena, accumulated_count);
}
```

## AST Module Compatibility

In `Lib/ast.py`, the `operations_count` attribute is hidden from `dump()` output since it's an internal implementation detail:

```python
def dump(node, annotate_fields=True, include_attributes=False, *, indent=None):
    def _format(node, level=0):
        # ...
        if include_attributes and node._attributes:
            for name in node._attributes:
                # Skip internal sandbox-related attributes
                if name == 'operations_count':
                    continue
                # ... rest of attribute handling ...
```

## Generated Files

After modifying `Python.asdl`, the following files are regenerated:

- `Include/internal/pycore_ast.h` - AST structure definitions
- `Include/internal/pycore_ast_state.h` - AST state definitions
- `Python/Python-ast.c` - AST creation and traversal functions

Regenerate with: `make regen-ast`

# Drawbacks
[drawbacks]: #drawbacks

1. **Grammar complexity**: Many grammar rules need updating when changing what counts.

2. **ASDL change**: Adding `operations_count` to the AST definition affects all AST nodes, even when not using sandbox features.

3. **Learning curve**: Developers must understand EXTRA vs EXTRA_OP1 when modifying the grammar.

4. **Bytecode compatibility**: Code compiled with different `operations_count` logic produces different bytecode.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why AST Attributes vs. Hardcoded Compiler Calls?

**Alternative**: Keep hardcoded `ADDOP_SANDBOX_COUNT(c)` calls throughout the compiler.

- Rejected: Scattered, hard to maintain, prone to inconsistency.

**Chosen**: AST attributes provide a single source of truth for what counts.

## Why operations_count vs. Boolean Flag?

**Alternative**: Use `bool should_count` instead of `int operations_count`.

- Rejected: Can't handle folding accumulation; `1+2+3` would count as 1 instead of 2.

**Chosen**: Integer count enables proper accumulation during constant folding.

## Why Optional Attribute vs. Required?

**Alternative**: Make `operations_count` required on all nodes.

- Rejected: Breaks Python's `ast` module which creates nodes without sandbox attributes.

**Chosen**: `int?` makes it optional; defaults to 0 when not specified.

## Why Hide from ast.dump()?

**Alternative**: Show `operations_count` in `ast.dump()` output.

- Rejected: Pollutes output with internal implementation detail; breaks test expectations.

**Chosen**: Hide from dump to maintain backward compatibility and clean output.

# Prior art
[prior-art]: #prior-art

1. **Python's line/column tracking**: AST nodes already have `lineno`, `col_offset`, etc. as attributes. Adding `operations_count` follows the same pattern.

2. **Coverage.py instrumentation**: Uses AST transformation to add coverage tracking. Similar concept of AST-level instrumentation.

3. **Ethereum Solidity**: Gas costs are assigned at the AST level during compilation, similar to how `operations_count` is set during parsing.

4. **Babel (JavaScript)**: AST transformations with metadata attached to nodes.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should comprehensions have a non-zero `operations_count`? Currently they're 0 because iteration is handled separately.

2. Should there be a way to configure weights per operation type (e.g., Call costs 10, BinOp costs 1)?

3. Should `operations_count` be exposed through a public Python API for introspection?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Weighted Operations**: Extend `operations_count` to support per-type weights:
   ```python
   sys.sandbox.operation_weights = {'Call': 10, 'BinOp': 1, 'Attribute': 2}
   ```

2. **Operation Profiling**: Track which operation types consume the most budget.

3. **AST-level Cost Analysis**: Static analysis tools could use `operations_count` to estimate code cost without execution.

4. **Configurable Counting**: Allow users to specify which node types should count:
   ```python
   sys.sandbox.counted_operations = {'Call', 'BinOp', 'Attribute'}
   ```

5. **Cross-platform Determinism Testing**: Use `operations_count` to verify that the same source produces identical counts across platforms.

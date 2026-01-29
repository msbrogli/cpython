- Feature Name: sandbox-determinism
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

This document analyzes each sandbox counter and limit for determinism - whether it produces the same value for the same source code regardless of Python version, bytecode compilation, platform, and architecture. This analysis is critical for applications that require reproducible execution costs across different environments.

# Motivation
[motivation]: #motivation

When using sandbox limits for cost accounting or resource metering, determinism is essential:

1. **Fair billing**: If execution cost varies by platform, users may be charged inconsistently
2. **Reproducibility**: Test results should be consistent across CI environments
3. **Consensus**: Distributed systems may need to agree on execution costs
4. **Debugging**: Non-deterministic counts make debugging difficult

Understanding which counters are deterministic allows developers to choose the right limits for their use case.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Quick Reference

| Counter/Limit | Deterministic? | Safe for Cost Accounting? |
|---------------|----------------|---------------------------|
| `operation_count` | **YES** | **YES** |
| `iteration_count` | **YES** | **YES** |
| `statement_count` | **NO** | **NO** |
| `allocation_count` | **NO** | **NO** |
| Size limits | **YES** | **YES** |
| Type restrictions | **YES** | **YES** |

## Recommended Configuration for Deterministic Execution

```python
import sys

# Compile with SANDBOX_COUNT flag for deterministic operation counting
PyCF_SANDBOX_COUNT = 0x8000
code = compile(source, "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)

# Set deterministic limits only
sys.sandbox.set_limits(
    # Deterministic execution limits
    max_operations=100_000,      # AST-based counting
    max_iterations=1_000_000,    # Iterator-based counting

    # Deterministic size limits
    max_int_digits=1000,
    max_str_length=100_000,
    max_bytes_length=100_000,
    max_list_size=10_000,
    max_dict_size=10_000,
    max_set_size=10_000,
    max_tuple_size=10_000,

    # Deterministic type restrictions
    allow_float=True,
    allow_complex=True,
    allow_dunder_access=False,
)

# WARNING: Do NOT rely on these for deterministic cost accounting:
# max_statements=X     # Non-deterministic!
# max_allocations=X    # Non-deterministic!
```

## When Non-Deterministic Limits Are Acceptable

Statement and allocation limits are still useful for:

- **Soft timeouts**: Preventing runaway execution without exact guarantees
- **Memory pressure protection**: Limiting total allocations as a safety net
- **Defense in depth**: Additional protection layer alongside deterministic limits

Just don't rely on exact counts being reproducible across environments.

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## 1. `operation_count` (via SANDBOX_COUNT opcode)

### Verdict: DETERMINISTIC

### How It Works

The compiler emits `SANDBOX_COUNT` opcodes at specific AST nodes when the `PyCF_SANDBOX_COUNT` flag is set. Each opcode execution increments `operation_count`.

### Counted AST Nodes

**Statements:**
- `FunctionDef`, `AsyncFunctionDef`, `ClassDef`
- `Return`, `Delete`, `Assign`, `AugAssign`, `AnnAssign`
- `For`, `AsyncFor`, `While`, `If`, `Match`
- `With`, `AsyncWith`, `Try`, `TryStar`
- `Raise`, `Assert`, `Import`, `ImportFrom`
- `Pass`, `Break`, `Continue`

**Expressions:**
- `BoolOp`, `BinOp`, `UnaryOp`, `Compare`
- `Attribute`, `Subscript`
- All function/method calls

### Why It's Deterministic

1. **Based on AST structure**: The AST is parsed directly from source code
2. **Source-determined**: Same source code = same AST = same opcode count
3. **Independent of optimization**: AST structure doesn't change with optimization level
4. **Platform-independent**: AST parsing is consistent across platforms

### Caveats

- AST model changes between **major** Python versions could affect counts
- Within a fixed Python version, completely deterministic

### Example

```python
# This code always produces exactly 7 operations:
x = 1 + 2       # 2 ops: Assign + BinOp
y = x * 3       # 2 ops: Assign + BinOp
if y > 5:       # 2 ops: If + Compare
    print(y)    # 1 op: Call
```

---

## 2. `iteration_count` (iterator wrapper)

### Verdict: DETERMINISTIC

### How It Works

All iterators are wrapped via `_PySandbox_WrapIterator()` when in sandbox scope. Each call to `tp_iternext` increments `iteration_count`.

### Why It's Deterministic

1. **Data-driven**: Number of yields is determined by the data being iterated
2. **Semantic counting**: Counts actual items, not implementation details
3. **Stable protocol**: Iterator protocol hasn't changed

### Examples of Predictable Counts

| Code | Iteration Count |
|------|-----------------|
| `for i in range(n): pass` | n |
| `sum(x for x in range(n))` | n |
| `list(iterable)` | len(iterable) |
| `''.join(strings)` | len(strings) |
| `min(values)` | len(values) |

### Why It's Not Affected By

- **Python version**: Iterator protocol is stable
- **Platform/architecture**: Count is semantic, not implementation-dependent
- **Bytecode**: Iteration count is about data flow, not opcodes

---

## 3. `statement_count` (line tracing)

### Verdict: NOT DETERMINISTIC

### How It Works

Called from `ceval.c` during bytecode execution via the `DO_TRACING` mechanism. Counts on:
- Line number changes
- Backward jumps (loop iterations)

### Implementation Detail

```c
int lastline = _PyCode_LineNumberFromArray(frame->f_code, instr_prev);
int line = _PyCode_LineNumberFromArray(frame->f_code, _PyInterpreterFrame_LASTI(frame));

if (line != -1 && (line != lastline || _PyInterpreterFrame_LASTI(frame) <= instr_prev)) {
    _PySandbox_CheckScopeStatement();
}
```

### Why It's NOT Deterministic

1. **Depends on bytecode instruction sequence**
   - Different compilation options = different bytecode
   - Different bytecode = different instruction positions = different line transitions

2. **Depends on line number table**
   - Line table format changed between Python 3.10/3.11
   - Same source may have different line mappings

3. **Backward jump detection depends on instruction positions**
   - `_PyInterpreterFrame_LASTI(frame) <= instr_prev` compares bytecode offsets
   - Different bytecode = different offsets

4. **Platform-specific optimizations**
   - Peephole optimizer behavior may vary
   - Specialized opcodes affect instruction sequence

### Example of Non-Determinism

```python
for i in range(3):
    x = i + 1
```

Could produce different statement counts depending on:
- Whether loop is optimized
- How line numbers are mapped to bytecode
- Backward jump detection based on bytecode offsets

---

## 4. `allocation_count` (GC tracking)

### Verdict: NOT DETERMINISTIC

### How It Works

Called from `gc_alloc()` in `gcmodule.c` for each GC-tracked object allocation.

### Why It's NOT Deterministic

1. **Internal Python allocations vary**
   - String interning behavior differs
   - Small integer caching differs
   - Frame object allocation patterns differ

2. **GC implementation details**
   - Which objects get tracked varies by version
   - Container implementation changes affect allocations
   - Exception handling allocates differently

3. **Platform differences**
   - Memory alignment may affect allocation patterns
   - Some types may have platform-specific implementations

4. **Version differences**
   - Python 3.11 introduced structural changes (frame layout, etc.)
   - String representation changes between versions
   - Dict implementation changes

### Example of Non-Determinism

```python
x = [1, 2, 3]
y = {"a": 1, "b": 2}
```

Number of internal allocations depends on:
- List/dict implementation
- String interning for "a", "b"
- Frame objects, code objects, etc.

---

## 5. Size Limits

### Verdict: DETERMINISTIC

| Limit | What It Measures | Why Deterministic |
|-------|------------------|-------------------|
| `max_int_digits` | PyLong internal digits (~30 bits each) | Internal digit count is mathematically determined |
| `max_str_length` | Unicode code points | Based on string content |
| `max_bytes_length` | Byte count | Based on content |
| `max_list_size` | Item count | Based on content |
| `max_dict_size` | Key count | Based on content |
| `max_set_size` | Element count | Based on content |
| `max_tuple_size` | Item count | Based on content |

All size limits measure **semantic properties** of data, not implementation details. `len(my_list)` is the same regardless of platform.

---

## 6. Type Restrictions

### Verdict: DETERMINISTIC

| Restriction | What It Checks | Why Deterministic |
|-------------|----------------|-------------------|
| `allow_float` | `type == &PyFloat_Type` | Type identity is stable |
| `allow_complex` | `type == &PyComplex_Type` | Type identity is stable |
| `allow_dunder_access` | Name contains `__` | String pattern matching |

---

## Determinism Matrix

| Feature | Same Source | Same Python Version | Same Platform | Cross-Version | Cross-Platform |
|---------|-------------|---------------------|---------------|---------------|----------------|
| `operation_count` | ✓ | ✓ | ✓ | ~* | ✓ |
| `iteration_count` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `statement_count` | ✓ | ~ | ~ | ✗ | ~ |
| `allocation_count` | ~ | ~ | ~ | ✗ | ✗ |
| Size limits | ✓ | ✓ | ✓ | ✓ | ✓ |
| Type restrictions | ✓ | ✓ | ✓ | ✓ | ✓ |

Legend:
- ✓ = Deterministic
- ~ = Mostly deterministic, minor variations possible
- ✗ = Not deterministic
- \* = Deterministic within minor versions, may change across major versions

# Drawbacks
[drawbacks]: #drawbacks

1. **Complexity**: Users must understand which limits are deterministic
2. **Documentation burden**: Need to clearly communicate determinism properties
3. **Feature disparity**: Deterministic limits (operations) require extra compilation step

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Not Make All Counters Deterministic?

**Statement counting**: Would require significant changes to CPython's tracing mechanism. Line-based tracing is inherently tied to bytecode structure.

**Allocation counting**: Would require tracking only "user-visible" allocations, which is complex to define and implement. Python's memory management is intentionally an implementation detail.

## Why Keep Non-Deterministic Counters?

They're still valuable for:
- Defense in depth
- Soft limits / safety nets
- Single-environment consistency (same machine, same Python version)

# Prior art
[prior-art]: #prior-art

1. **Ethereum Gas Metering**: Completely deterministic - each opcode has fixed cost. Achieved by having full control over the VM.

2. **WebAssembly Fuel**: Deterministic instruction counting. Similar to our `operation_count`.

3. **Python's `sys.settrace()`**: Non-deterministic by nature, as we document for `statement_count`.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should we deprecate or warn when using non-deterministic limits in contexts requiring determinism?

2. Should there be a "strict determinism" mode that only allows deterministic limits?

3. How should AST changes between major Python versions be communicated?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Determinism Warnings**: Emit warnings when non-deterministic limits might cause issues

2. **Operation Weights**: Allow configuring per-operation costs for more sophisticated metering

3. **Version-Stable Counting**: Define a "stable subset" of operations that won't change across versions

4. **Formal Specification**: Document exact counting semantics as part of Python's language specification

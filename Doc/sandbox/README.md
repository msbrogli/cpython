# CPython Sandbox Documentation

This directory contains RFC-style documentation for each module of the CPython sandbox implementation. Each RFC follows the standard Hathor RFC template and provides comprehensive documentation for its respective feature.

## RFC Index

| RFC | Module | Description |
|-----|--------|-------------|
| [RFC-001](RFC-001-sandbox-core.md) | Core | State management, scope tracking, suspend/resume |
| [RFC-002](RFC-002-sandbox-limits.md) | Limits | Size limits, type restrictions, scoped counters |
| [RFC-003](RFC-003-sandbox-frozen.md) | Frozen | Frozen mode, auto-mutable mode |
| [RFC-004](RFC-004-sandbox-iter.md) | Iterator | Iterator wrapping, iteration limits |
| [RFC-005](RFC-005-sandbox-imports.md) | Imports | Import restrictions, allowlist |
| [RFC-006](RFC-006-sandbox-opcodes.md) | Opcodes | Opcode restriction, banned opcodes |
| [RFC-007](RFC-007-sandbox-hooks.md) | Hooks | Object creation hooks |
| [RFC-008](RFC-008-sandbox-exceptions.md) | Exceptions | Exception hierarchy |
| [RFC-009](RFC-009-sandbox-operations.md) | Operations | SANDBOX_COUNT opcode, operation counting |
| [RFC-010](RFC-010-sandbox-determinism.md) | Determinism | Counter determinism analysis |

## Quick Start

```python
import sys

# Configure limits (allow_io=False and allow_unsafe=False are defaults)
sys.sandbox.set_limits(
    max_int_digits=100,
    max_str_length=100_000,
    max_list_size=1_000_000,
    max_statements=100_000,
    max_iterations=1_000_000,
    allow_dunder_access=False,
    # allow_io=False,     # Default: blocks file/socket/fd operations
    # allow_unsafe=False, # Default: blocks compile(), gc introspection
)

# Register sandbox scope
sys.sandbox.add_filename("<sandbox>")

# Compile and execute untrusted code
code = compile(untrusted_source, "<sandbox>", "exec")

try:
    with sys.sandbox.scope():
        exec(code)
except SandboxError as e:
    print(f"Sandbox violation: {e}")
```

## Implementation Files

### Core Implementation

| File | Lines | Purpose |
|------|-------|---------|
| `Python/sandbox_core.c` | ~420 | State management, scope tracking |
| `Python/sandbox_limits.c` | ~570 | Size limits, counters, checks |
| `Python/sandbox_frozen.c` | ~180 | Frozen mode, auto-mutable |
| `Python/sandbox_iter.c` | ~190 | Iterator wrapper |
| `Python/sandbox_imports.c` | ~460 | Import restrictions |
| `Python/sandbox_opcodes.c` | ~190 | Opcode restrictions |
| `Python/sandbox_pyapi.c` | ~1040 | Python API (sys.sandbox) |

### Headers

| File | Purpose |
|------|---------|
| `Include/internal/pycore_sandbox.h` | Public API declarations |
| `Include/internal/pycore_sandbox_impl.h` | Inline helpers |

### Integration Points

| File | Integration |
|------|-------------|
| `Objects/longobject.c` | Integer size check |
| `Objects/unicodeobject.c` | String length check |
| `Objects/listobject.c` | List size check |
| `Objects/dictobject.c` | Dict size check |
| `Objects/setobject.c` | Set size check |
| `Objects/tupleobject.c` | Tuple size check |
| `Objects/bytesobject.c` | Bytes length check |
| `Objects/floatobject.c` | Float type check |
| `Objects/typeobject.c` | Type check, creation hook, frozen |
| `Objects/object.c` | Frozen mode check |
| `Objects/abstract.c` | Iterator wrapping, dunder check |
| `Objects/descrobject.c` | Dunder check, frozen check |
| `Objects/exceptions.c` | Sandbox exceptions |
| `Python/ceval.c` | Statement/operation counting, opcode check |
| `Python/compile.c` | SANDBOX_COUNT emission |
| `Modules/gcmodule.c` | Allocation counting |
| `Modules/_io/_iomodule.c` | I/O check (open) |
| `Modules/_io/fileio.c` | I/O check (FileIO) |
| `Modules/socketmodule.c` | I/O check (socket) |
| `Modules/posixmodule.c` | I/O check (os.open, os.read, etc.) |

## Exception Hierarchy

```
Exception
 └── SandboxError
      ├── SandboxOverflowError    (size/length exceeded)
      ├── SandboxMemoryError      (allocation limit)
      ├── SandboxRuntimeError     (statement/iteration/operation/opcode)
      ├── SandboxTypeError        (forbidden type)
      ├── SandboxAttributeError   (frozen/dunder)
      ├── SandboxSecurityError    (unsafe operation)
      └── SandboxImportError      (import blocked)
```

## Feature Summary

| Feature | RFC | Property/Method |
|---------|-----|-----------------|
| Integer limit | 002 | `max_int_digits` |
| String limit | 002 | `max_str_length` |
| Bytes limit | 002 | `max_bytes_length` |
| List limit | 002 | `max_list_size` |
| Dict limit | 002 | `max_dict_size` |
| Set limit | 002 | `max_set_size` |
| Tuple limit | 002 | `max_tuple_size` |
| Float restriction | 002 | `allow_float` |
| Complex restriction | 002 | `allow_complex` |
| Dunder blocking | 002 | `allow_dunder_access` |
| Unsafe blocking | 002 | `allow_unsafe` |
| I/O blocking | 002 | `allow_io` |
| Statement limit | 002 | `max_statements` |
| Allocation limit | 002 | `max_allocations` |
| Iteration limit | 004 | `max_iterations` |
| Operation limit | 009 | `max_operations` |
| Iteration as ops | 004 | `count_iterations_as_operations` |
| Global freeze | 003 | `frozen_mode` |
| Per-object freeze | 003 | `freeze()`, `is_frozen()` |
| Auto-mutable | 003 | `auto_mutable` |
| Mutable override | 003 | `set_mutable()` |
| Import restriction | 005 | `import_restrict_mode`, `allowed_imports` |
| Submodule imports | 005 | `import_allow_submodules` |
| Opcode restriction | 006 | `opcode_restrict_mode`, `banned_opcodes` |
| Creation hook | 007 | `creation_hook` |
| Scope management | 001 | `scope()`, `add_filename()`, etc. |
| Suspend/resume | 001 | `suspend()`, `resume()`, `suspended_limits()` |
| Counter reset | 001 | `reset_counts()`, `reset()` |

## Determinism Notes

| Counter | Deterministic | Safe for Cost Accounting |
|---------|---------------|--------------------------|
| `operation_count` | **Yes** | **Yes** - AST-based, compiler-emitted |
| `iteration_count` | **Yes** | **Yes** - Counts actual yields |
| `statement_count` | No | No - Depends on bytecode layout |
| `allocation_count` | No | No - Depends on Python internals |
| Size limits | **Yes** | **Yes** - Semantic values |
| Type restrictions | **Yes** | **Yes** - Type-based checks |

For deterministic cost accounting, prefer `max_operations` with `PyCF_SANDBOX_COUNT`.

See [RFC-010: Determinism Analysis](RFC-010-sandbox-determinism.md) for detailed analysis of each counter's determinism properties, including:
- Why `operation_count` and `iteration_count` are deterministic
- Why `statement_count` and `allocation_count` are NOT deterministic
- Recommended configuration for deterministic execution
- Cross-version and cross-platform considerations

## Testing

```bash
# Run all sandbox tests
./python -m unittest discover -s Lib/test/test_sandbox -v

# Run specific module tests
./python -m unittest test.test_sandbox.test_limits -v
./python -m unittest test.test_sandbox.test_frozen_mode -v
./python -m unittest test.test_sandbox.test_operations -v
```

## Porting to Other Python Versions

See the "Porting Guide" section in the original `SANDBOX_IMPLEMENTATION_GUIDE.md` for step-by-step instructions on porting to Python 3.12, 3.13, or later versions.

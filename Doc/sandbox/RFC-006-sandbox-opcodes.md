- Feature Name: sandbox-opcodes
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox opcodes module provides bytecode-level operation restriction through a bitmap of banned opcodes. When enabled, any attempt to execute a banned opcode from sandbox scope raises `SandboxRuntimeError`. This allows fine-grained control over what operations sandboxed code can perform.

# Motivation
[motivation]: #motivation

Some Python operations are dangerous regardless of the values involved:

1. **Imports**: `IMPORT_NAME`, `IMPORT_FROM`, `IMPORT_STAR` can load arbitrary code
2. **Attribute access**: `LOAD_ATTR`, `STORE_ATTR` can access dangerous attributes
3. **Global access**: `LOAD_GLOBAL`, `STORE_GLOBAL` can modify shared state
4. **Calls**: `CALL_FUNCTION` can invoke dangerous callables

While other sandbox features (import restrictions, frozen mode) address some concerns, opcode restriction provides defense-in-depth at the bytecode level. If sandboxed code somehow bypasses higher-level checks, opcode restriction provides a final barrier.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Enabling Opcode Restrictions

```python
import sys
import opcode

# Set banned opcodes (set of opcode integers)
sys.sandbox.banned_opcodes = {
    opcode.opmap['IMPORT_NAME'],
    opcode.opmap['IMPORT_FROM'],
    opcode.opmap['IMPORT_STAR'],
}

# Enable opcode restriction mode
sys.sandbox.opcode_restrict_mode = True

sys.sandbox.add_filename("<sandbox>")

code = compile("import os", "<sandbox>", "exec")

try:
    exec(code)
except SandboxRuntimeError as e:
    print(e)  # "Opcode 108 is not allowed in sandbox scope"
```

## Common Opcode Sets

### Block All Imports

```python
import opcode

IMPORT_OPCODES = {
    opcode.opmap['IMPORT_NAME'],
    opcode.opmap['IMPORT_FROM'],
    opcode.opmap['IMPORT_STAR'],
}

sys.sandbox.banned_opcodes = IMPORT_OPCODES
sys.sandbox.opcode_restrict_mode = True
```

### Block Attribute Mutation

```python
ATTR_MUTATION_OPCODES = {
    opcode.opmap['STORE_ATTR'],
    opcode.opmap['DELETE_ATTR'],
}

sys.sandbox.banned_opcodes = ATTR_MUTATION_OPCODES
```

### Block Global Mutation

```python
GLOBAL_MUTATION_OPCODES = {
    opcode.opmap['STORE_GLOBAL'],
    opcode.opmap['DELETE_GLOBAL'],
    opcode.opmap['STORE_NAME'],
    opcode.opmap['DELETE_NAME'],
}

sys.sandbox.banned_opcodes = GLOBAL_MUTATION_OPCODES
```

## Checking Current Configuration

```python
# Get banned opcodes
banned = sys.sandbox.banned_opcodes
print(banned)  # frozenset({108, 109, 84})

# Check if mode is active
print(sys.sandbox.opcode_restrict_mode)  # True/False
```

## Combining with Other Restrictions

Opcode restrictions work alongside other sandbox features:

```python
import sys
import opcode

# Multi-layered protection
sys.sandbox.set_config(
    max_operations=10000,
    allow_dunder_access=False,
)

sys.sandbox.banned_opcodes = {opcode.opmap['IMPORT_NAME']}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.frozen_mode = True

# Now sandboxed code cannot:
# - Execute more than 10000 operations (with PyCF_SANDBOX_COUNT flag)
# - Access __dunder__ attributes
# - Use IMPORT_NAME opcode
# - Modify any attributes
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

### Opcode Bitmap

256-bit bitmap for O(1) opcode lookup:

```c
typedef struct {
    uint32_t bits[8];  /* 8 * 32 = 256 bits */
} _PySandboxOpcodeSet;

#define _PySandbox_OpcodeSet_HAS(set, op) \
    ((set)->bits[(op) >> 5] & (1U << ((op) & 31)))

#define _PySandbox_OpcodeSet_SET(set, op) \
    ((set)->bits[(op) >> 5] |= (1U << ((op) & 31)))

#define _PySandbox_OpcodeSet_CLEAR(set, op) \
    ((set)->bits[(op) >> 5] &= ~(1U << ((op) & 31)))

#define _PySandbox_OpcodeSet_ZERO(set) \
    memset((set)->bits, 0, sizeof((set)->bits))
```

### State Storage

```c
typedef struct {
    /* ... other fields ... */
    int opcode_restrict_mode;            /* 1 = active, 0 = off */
    _PySandboxOpcodeSet banned_opcodes;  /* Bitmap of banned opcodes */
    /* ... */
} _PySandboxState;
```

## Opcode Check Function

```c
int
_PySandbox_CheckOpcode(int opcode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast exit: mode not active */
    if (!sandbox->opcode_restrict_mode) {
        return 0;
    }

    /* Fast exit: suspended or in recursive check */
    if (sandbox->suspend_depth || sandbox->suppress_checks) {
        return 0;
    }

    /* Fast exit: opcode not banned (bitmap check) */
    if (!_PySandbox_OpcodeSet_HAS(&sandbox->banned_opcodes, opcode)) {
        return 0;
    }

    /* Check if in sandbox scope */
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    /* Banned opcode in sandbox scope - raise error */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Opcode %d is not allowed in sandbox scope", opcode);
    sandbox->suppress_checks = 0;
    return -1;
}
```

## Opcode Dispatch Check

Called from `Python/ceval.c` in the opcode dispatch loop:

```c
/* In ceval.c tracing/dispatch section */
static inline int
_PySandbox_CheckOpcodeDispatch(int opcode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || !interp->sandbox.opcode_restrict_mode) {
        return 0;  /* Fast path when disabled */
    }
    return _PySandbox_CheckOpcode(opcode);
}
```

The check is called before each opcode execution when tracing is active:

```c
TARGET(IMPORT_NAME) {
    /* Check runs via DO_TRACING or dedicated check */
    if (_PySandbox_CheckOpcodeDispatch(IMPORT_NAME) < 0) {
        goto error;
    }
    /* ... normal opcode implementation ... */
}
```

## C API

```c
/* Enable/disable opcode restriction mode */
void PySandbox_SetOpcodeRestrictMode(int mode);
int PySandbox_GetOpcodeRestrictMode(void);

/* Set banned opcodes from Python set of integers (or NULL to clear) */
int PySandbox_SetBannedOpcodes(PyObject *opcode_set);

/* Get banned opcodes as frozenset */
PyObject *PySandbox_GetBannedOpcodes(void);

/* Check if opcode is allowed (called from ceval.c) */
int _PySandbox_CheckOpcode(int opcode);
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `opcode_restrict_mode` | bool | False | Enable opcode checking |
| `banned_opcodes` | frozenset | None | Set of banned opcode integers |

### Setting Banned Opcodes

```python
# From list
sys.sandbox.banned_opcodes = [108, 109, 84]

# From set
sys.sandbox.banned_opcodes = {108, 109, 84}

# From opcode module
import opcode
sys.sandbox.banned_opcodes = {opcode.opmap['IMPORT_NAME']}

# Clear (allow all opcodes)
sys.sandbox.banned_opcodes = None
```

## Performance

### Fast Exits

The check function has multiple fast exits to minimize overhead:

1. **Mode off**: Single pointer dereference + comparison
2. **Suspended**: Single comparison
3. **Opcode not banned**: Single bitmap lookup (O(1))
4. **Out of scope**: Set lookup (O(1) average)

### Bitmap Efficiency

The 256-bit bitmap allows O(1) opcode checking:
- 8 `uint32_t` values = 32 bytes
- Bit test: `bits[op >> 5] & (1 << (op & 31))`
- No memory allocation, no hash computation

## Common Opcodes Reference

| Opcode | Name | Purpose |
|--------|------|---------|
| 108 | `IMPORT_NAME` | Import a module |
| 109 | `IMPORT_FROM` | Import a name from module |
| 84 | `IMPORT_STAR` | Import all names (`from X import *`) |
| 95 | `STORE_ATTR` | Set attribute |
| 96 | `DELETE_ATTR` | Delete attribute |
| 116 | `LOAD_GLOBAL` | Load global variable |
| 117 | `STORE_GLOBAL` | Set global variable |
| 118 | `DELETE_GLOBAL` | Delete global variable |

Use `opcode.opmap` to get current Python version's opcode numbers.

## Exception Type

`SandboxRuntimeError` is raised for banned opcodes:

```
SandboxRuntimeError: Opcode 108 is not allowed in sandbox scope
```

# Security Considerations
[security-considerations]: #security-considerations

## Specialized Opcode Mapping (P0 Critical)

CPython's adaptive interpreter (PEP 659) creates specialized variants of opcodes
for performance. Each generic opcode (e.g., `LOAD_ATTR`) has multiple specialized
forms (e.g., `LOAD_ATTR_INSTANCE_VALUE`, `LOAD_ATTR_SLOT`).

**Security Requirement:** Every security check added to a generic opcode MUST also
be added to ALL its specialized variants, OR specialized opcodes must deoptimize
when security checks are needed.

### Affected Opcode Families

| Generic Opcode | Specialized Variants |
|----------------|---------------------|
| `LOAD_ATTR` | 4 specialized variants: `LOAD_ATTR_INSTANCE_VALUE`, `LOAD_ATTR_MODULE`, `LOAD_ATTR_WITH_HINT`, `LOAD_ATTR_SLOT` |
| `STORE_ATTR` | 3 specialized variants: `STORE_ATTR_INSTANCE_VALUE`, `STORE_ATTR_WITH_HINT`, `STORE_ATTR_SLOT` |
| `LOAD_METHOD` | 5 specialized variants: `LOAD_METHOD_WITH_VALUES`, `LOAD_METHOD_WITH_DICT`, `LOAD_METHOD_NO_DICT`, `LOAD_METHOD_MODULE`, `LOAD_METHOD_CLASS` |
| `BINARY_SUBSCR` | 4 specialized variants |
| `STORE_SUBSCR` | 2 specialized variants |
| `LOAD_GLOBAL` | 2 specialized variants |
| `COMPARE_OP` | 3 specialized variants |
| `CALL/PRECALL` | 13+ specialized variants |

### Mapping Location

`Python/specialize.c` line 20-32 defines `_PyOpcode_Adaptive[]` which maps generic
opcodes to their adaptive entry points. The actual specialization functions are
`_Py_Specialize_*()` in the same file.

### Recommended Mitigation Pattern

Use the `DEOPT_IF(sandbox_condition, GENERIC_OPCODE)` pattern at the start of each
specialized opcode to automatically fall back to the protected generic implementation
when sandbox restrictions are active:

```c
TARGET(LOAD_ATTR_INSTANCE_VALUE) {
    assert(cframe.use_tracing == 0);
    /* Deoptimize if sandbox dunder blocking is active */
    DEOPT_IF(!tstate->interp->sandbox.config.allow_dunder_access ||
             !tstate->interp->sandbox.config.allow_unsafe, LOAD_ATTR);
    // ... existing specialized code (unchanged) ...
}
```

This approach:
- Ensures all security checks in the generic opcode are applied
- Maintains full performance for non-sandboxed code
- Provides a simple, auditable pattern (every specialized opcode starts with `DEOPT_IF`)
- Automatically benefits from any future security fixes to generic opcodes

### Why Deoptimization is Preferred

**Option 1: Add security checks to each specialized opcode**
- Pros: Fine-grained control
- Cons: Must modify 15+ opcodes, easy to miss one during future updates, ongoing maintenance burden

**Option 2: Deoptimize when sandbox is active (Recommended)**
- Pros: Simple one-line addition, leverages existing security checks, easier to audit
- Cons: Performance penalty when sandbox is active (acceptable trade-off for sandboxed code)

**Option 3: Disable specialization entirely**
- Pros: Single point of control
- Cons: Significant performance penalty, hard to implement cleanly

# Drawbacks
[drawbacks]: #drawbacks

1. **Version Dependency**: Opcode numbers change between Python versions. Code using raw numbers is not portable.

2. **Tracing Overhead**: When enabled, opcode checking adds overhead to every instruction dispatch.

3. **Coarse Granularity**: Can only ban opcodes entirely, not based on operands (e.g., can't allow `LOAD_ATTR` for some attributes but not others).

4. **Defense in Depth Only**: Opcode restriction alone is insufficient; should be combined with other protections.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Bitmap vs. Set?

**Set approach**:
```c
PyObject *banned_opcodes;  /* Python set */
int is_banned = PySet_Contains(banned_opcodes, PyLong_FromLong(opcode));
```
- Rejected: Memory allocation, hash computation, GIL considerations per check.

**Bitmap approach** (chosen):
```c
uint32_t bits[8];
int is_banned = bits[op >> 5] & (1U << (op & 31));
```
- O(1) constant time
- No memory allocation
- Single memory read
- Cache-friendly

## Why 256 Bits?

Python opcodes are single bytes (0-255). 256 bits covers all possible opcodes with minimal space (32 bytes).

## Why Separate Mode Flag?

```c
if (!sandbox->opcode_restrict_mode) return 0;  /* Fast exit */
```

Could check `banned_opcodes == empty`, but separate flag allows:
- Faster check (no bitmap scan)
- Clear enable/disable semantics
- Prepare banned list before enabling

# Prior art
[prior-art]: #prior-art

1. **Java Bytecode Verifier**: Validates bytecode before execution; similar concept of instruction-level security.

2. **WebAssembly**: Has a strict set of allowed instructions; sandboxed by design.

3. **eBPF Verifier**: Linux kernel verifies BPF bytecode before execution.

4. **Seccomp-BPF**: Linux syscall filtering using BPF; similar bitmap-based filtering.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be a "safe opcode set" preset for common use cases?

2. How to handle opcode number changes across Python versions?

3. Should extended opcodes (with `EXTENDED_ARG`) be handled specially?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Opcode Argument Filtering**: Ban opcodes only for specific arguments (e.g., `LOAD_ATTR` only for certain attribute names).

2. **Opcode Quotas**: Limit how many times certain opcodes can execute.

3. **Opcode Replacement**: Replace banned opcodes with safe alternatives at load time.

4. **JIT Integration**: Integrate with JIT compilers to enforce restrictions in compiled code.

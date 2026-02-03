- Feature Name: sandbox-core
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox core module provides the foundational state management, scope tracking, and suspend/resume functionality for the CPython sandbox system. It manages the `_PySandboxState` structure within `PyInterpreterState` and provides the infrastructure for filename-based scope tracking.

# Motivation
[motivation]: #motivation

Executing untrusted Python code requires a mechanism to track which code is "sandboxed" versus trusted. The core module solves this by:

1. **Scope Tracking**: Only sandboxed code (identified by filename) is subject to limits
2. **State Management**: Centralized storage for all sandbox configuration and counters
3. **Suspend/Resume**: Allows trusted code to temporarily bypass limits (e.g., during stdlib operations)
4. **Counter Reset**: Enables reusing the sandbox for multiple executions

Without scope tracking, limits would apply globally, breaking legitimate operations in trusted code paths.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Basic Usage

The sandbox uses filename-based scope tracking. Code is considered "in scope" when its `co_filename` is registered. **Important:** The sandbox must be explicitly enabled for limits to be enforced.

```python
import sys

# Register a filename for sandbox tracking
sys.sandbox.add_filename("<sandbox>")

# Enable the sandbox (disabled by default)
sys.sandbox.enable()

# Compile code with that filename
code = compile("x = 1 + 2", "<sandbox>", "exec")

# Now this code is subject to sandbox limits
exec(code)

# Clear scope when done
sys.sandbox.clear_filenames()
```

Note: `sys.sandbox.enable()` must be called before sandbox limits are enforced. By default, the sandbox is disabled even if limits are configured.

## Context Manager (Recommended)

The `scope()` context manager simplifies scope management:

```python
import sys

code = compile("x = 1 + 2", "<sandbox>", "exec")

sys.sandbox.add_filename("<sandbox>")
with sys.sandbox.scope():
    # Code compiled with "<sandbox>" filename is now in scope
    exec(code)
# Scope automatically cleared on exit
```

## Suspend/Resume for Trusted Operations

When sandboxed code calls trusted library functions, you can suspend limits:

```python
import sys

def trusted_helper():
    # Temporarily bypass all sandbox limits
    sys.sandbox.suspend()
    try:
        # Do trusted operations without limit checks
        result = expensive_computation()
    finally:
        sys.sandbox.resume()
    return result

# Or use the context manager
def trusted_helper_v2():
    with sys.sandbox.suspended_limits():
        return expensive_computation()
```

Suspend calls are nested-counted:
```python
sys.sandbox.suspend()   # suspend_depth = 1
sys.sandbox.suspend()   # suspend_depth = 2
sys.sandbox.resume()    # suspend_depth = 1
sys.sandbox.resume()    # suspend_depth = 0 (limits active again)
```

## Resetting State

Reset counters between executions:
```python
sys.sandbox.reset_counts()  # Reset counters only
sys.sandbox.reset()         # Reset everything to defaults
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

### `_PySandboxState`

Located in `Include/internal/pycore_sandbox.h`:

```c
/* Field ordering optimized for cache locality:
 * - Hot fields (checked on every enforcement) are placed first
 * - enabled, suppress_checks, suspend_depth are checked by _PySandbox_IsEnforced()
 */
typedef struct {
    /* Hot fields first for cache locality */
    int enabled;                        /* Master enable flag (0=disabled, 1=active) */
    int suppress_checks;                /* Recursion prevention */
    int suspend_depth;                  /* Suspend depth counter (nested) */
    _PySandboxConfig config;            /* Configuration values */
    _PySandboxCounters counters;        /* Runtime counters */
    /* Less frequently accessed fields */
    _PyObjectCreationHook creation_hook;
    int frozen_mode;                    /* Global attribute freeze */
    int auto_mutable;                   /* Auto-mark new objects as mutable */
    int opcode_restrict_mode;           /* Opcode restriction active */
    _PySandboxOpcodeSet allowed_opcodes; /* 256-bit opcode bitmap */
    PyObject *registered_filenames;     /* Python set of filenames */
    PyObject *allowed_imports;          /* Python set of (module, name) tuples */
    PyObject *allowed_modules;          /* Python frozenset of allowed module names */
    PyObject *mutable_objects;          /* Objects allowed mutation in frozen mode */
    PyObject *frozen_objects;           /* Individually frozen objects */
} _PySandboxState;
```

### State Storage

Sandbox state is stored per-interpreter in `PyInterpreterState`:

```c
struct _is {
    /* ... other fields ... */
    _PySandboxState sandbox;
    /* ... other fields ... */
};
```

## Core C API

### Initialization/Finalization

```c
/* Initialize sandbox state during interpreter creation */
void _PySandbox_Init(PyInterpreterState *interp);

/* Clean up sandbox state during interpreter finalization */
void _PySandbox_Fini(PyInterpreterState *interp);

/* Lazy-initialize the iterator wrapper type */
int _PySandbox_InitWrapperType(void);
```

### Scope Management

```c
/* Add current frame's filename and reset counters */
int _PySandbox_EnterScope(void);

/* Clear all registered filenames */
int _PySandbox_ExitScope(void);

/* Check if current frame is in sandbox scope */
int _PySandbox_IsInScope(void);

/* Add current frame's filename to scope (no counter reset) */
int _PySandbox_AddFrameToScope(void);

/* Manually register/unregister filenames */
int _PySandbox_AddFilename(PyObject *filename);
int _PySandbox_RemoveFilename(PyObject *filename);
void _PySandbox_ClearFilenames(void);

/* Security: prevent in-scope configuration changes */
int _PySandbox_CheckConfigModification(void);
```

### Enable/Disable

```c
/* Enable sandbox (set enabled=1) */
void PySandbox_Enable(void);

/* Disable sandbox (set enabled=0) */
void PySandbox_Disable(void);

/* Check if sandbox is enabled */
int PySandbox_IsEnabled(void);
```

### Enforcement Check Macro

```c
/* Check if sandbox enforcement is active.
 * Returns true when:
 * - enabled=1 (sandbox is turned on)
 * - suppress_checks=0 (not in recursive error handling)
 * - suspend_depth=0 (not temporarily bypassed)
 */
#define _PySandbox_IsEnforced(sandbox) \
    ((sandbox)->enabled && \
     !(sandbox)->suppress_checks && \
     (sandbox)->suspend_depth == 0)
```

### Suspend/Resume

```c
/* Suspend all limits, return new suspend count */
int PySandbox_Suspend(void);

/* Resume limits, return new suspend count */
int PySandbox_Resume(void);

/* Check if currently suspended */
int PySandbox_IsSuspended(void);
```

### Counter Management

```c
/* Reset all counters to 0 */
void _PySandbox_ResetCounters(void);

/* Reset all sandbox state to defaults */
void _PySandbox_Reset(PyInterpreterState *interp);
```

## Python API

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `enabled` | bool (read-only) | Master enable flag. False=disabled (default), True=active. Use `enable()`/`disable()` methods to modify. |
| `suspended` | bool (read-only) | True if sandbox is suspended |

### Methods

| Method | Description |
|--------|-------------|
| `enable()` | Enable sandbox enforcement |
| `disable()` | Disable sandbox enforcement |
| `enter_scope()` | Add current frame's filename, reset counters |
| `exit_scope()` | Clear all registered filenames |
| `in_scope()` | Check if current code is in scope |
| `add_frame()` | Add current frame's filename |
| `add_filename(name)` | Register a filename |
| `remove_filename(name)` | Unregister a filename |
| `clear_filenames()` | Clear all filenames |
| `suspend()` | Suspend limits, return count |
| `resume()` | Resume limits, return count |
| `reset_counts()` | Reset all counters to 0 |
| `reset()` | Reset all state to defaults |
| `scope()` | Context manager for scope |
| `suspended_limits()` | Context manager for suspend |

## Scope Tracking Implementation

### Filename Registration

The `registered_filenames` field is a Python `set` object (lazy-initialized on first use):

```c
static int
filename_is_registered(PyObject *registered_filenames, PyObject *filename)
{
    if (registered_filenames == NULL || filename == NULL) {
        return 0;
    }
    int result = PySet_Contains(registered_filenames, filename);
    if (result < 0) {
        PyErr_Clear();
        return 0;
    }
    return result;
}
```

### Frame Scope Check

The inline helper `frame_in_sandbox_scope()` in `pycore_sandbox_impl.h`:

```c
static inline int
frame_in_sandbox_scope(PyObject *registered_filenames, _PyInterpreterFrame *frame)
{
    if (registered_filenames == NULL || frame == NULL) {
        return 0;
    }
    /* Skip incomplete frames */
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    if (frame == NULL) {
        return 0;
    }
    return filename_is_registered(registered_filenames, frame->f_code->co_filename);
}
```

### Class Body Context Detection

The `CO_CLASS_BODY` flag (0x0040) identifies code objects that represent class bodies. This is set by the compiler in `Python/compile.c`:

```c
/* In compute_code_flags() */
if (ste->ste_type == ClassBlock) {
    flags |= CO_CLASS_BODY;
}
```

This flag is used by `_PySandbox_CheckDunderAccess(name, class_body_mode)` to control dunder access in class body context:

- `DUNDER_CLASS_NEVER` (0): Block all dunders (used by `LOAD_ATTR`, `STORE_ATTR`, etc.)
- `DUNDER_CLASS_WHITELIST` (1): Allow whitelisted dunders like `__name__`, `__module__`, `__slots__` (used by `LOAD_NAME`)
- `DUNDER_CLASS_ALL` (2): Allow ALL dunders for magic method definitions (used by `STORE_NAME`)

See RFC-002 for details on the class body dunder whitelist and mode semantics.

### Security: Configuration Modification Check

Sandboxed code cannot modify sandbox configuration:

```c
int
_PySandbox_CheckConfigModification(void)
{
    if (_PySandbox_IsInScope()) {
        PyErr_SetString(PyExc_SandboxSecurityError,
                        "Cannot modify sandbox configuration from within sandbox scope");
        return -1;
    }
    return 0;
}
```

### Security: Generator/Coroutine Frame Access

Generators, coroutines, and async generators expose their execution frame through `gi_frame`, `cr_frame`, and `ag_frame` attributes respectively. These frames contain local variables (`f_locals`) that could leak sensitive information if the generator/coroutine was created outside sandbox scope.

The sandbox blocks frame access from within sandbox scope:

```c
// Objects/genobject.c - _gen_getframe()
static PyObject *
_gen_getframe(PyGenObject *gen, const char *const name)
{
    /* Block frame access from sandbox scope to prevent information leakage.
     * Generators/coroutines created outside sandbox could expose their
     * local variables via gi_frame/cr_frame/ag_frame attributes. */
    if (_PySandbox_IsInScope()) {
        PyErr_SetString(PyExc_SandboxSecurityError,
            "generator/coroutine frame access is blocked in sandbox scope");
        return NULL;
    }
    // ... rest of implementation
}
```

**Blocked attributes:**
- `generator.gi_frame` → `SandboxSecurityError`
- `coroutine.cr_frame` → `SandboxSecurityError`
- `async_generator.ag_frame` → `SandboxSecurityError`

**Security rationale:** Without this check, passing a generator created outside sandbox to sandboxed code would allow the sandbox to access the generator's local variables, potentially leaking API keys, passwords, or other sensitive data stored in the creating scope.

## Implementation Files

| File | Purpose |
|------|---------|
| `Python/sandbox_core.c` | Core state management (~422 lines) |
| `Python/sandbox_limits.c` | Limit checks, dunder whitelist, metaclass check |
| `Include/internal/pycore_sandbox.h` | Public API declarations |
| `Include/internal/pycore_sandbox_impl.h` | Inline helpers |
| `Include/cpython/code.h` | CO_CLASS_BODY flag definition |

# Drawbacks
[drawbacks]: #drawbacks

1. **Filename Collision Risk**: If user code happens to use the same filename as sandboxed code, it would be incorrectly treated as in-scope. Mitigated by using unique filenames like `"<sandbox-uuid>"`.

2. **Manual Scope Management**: Users must remember to clear scope, though context managers help.

3. **Suspend Security**: Sandboxed code could potentially call `sys.sandbox.suspend()`. This is blocked by `_PySandbox_CheckConfigModification()`.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Filename-Based Scope?

**Alternative 1: Frame-Based Tracking**
Track specific frame objects instead of filenames.
- Rejected: Frame objects are transient; nested calls would lose scope.

**Alternative 2: Thread-Local Flag**
Set a "sandbox active" flag per-thread.
- Rejected: Doesn't handle calls between sandboxed and trusted code.

**Alternative 3: Execution Context**
Use Python's contextvars.
- Rejected: Too heavyweight; doesn't integrate well with C-level checks.

**Chosen: Filename-Based**
- Code compiled with a registered filename is always in scope
- Works across function calls, generators, and async
- O(1) set lookup performance
- Compatible with existing `co_filename` infrastructure

## Why Nested Suspend?

Nested suspend/resume allows composable trusted helpers:

```python
def outer():
    sys.sandbox.suspend()
    inner()  # Also calls suspend/resume internally
    sys.sandbox.resume()  # Still suspended until this returns

def inner():
    sys.sandbox.suspend()
    # ...
    sys.sandbox.resume()
```

Without nesting, `inner()` would prematurely re-enable limits.

# Prior art
[prior-art]: #prior-art

1. **Java SecurityManager**: Uses stack inspection to determine permissions. Similar concept but more heavyweight.

2. **JavaScript Realms/Compartments**: Isolated execution environments. Stronger isolation but different use case.

3. **Lua Sandboxing**: Uses environment manipulation. Simpler but less granular.

4. **PyPy Sandbox**: Process-level isolation. Stronger security but heavier overhead.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be a maximum nesting depth for suspend to prevent overflow?

2. Should `enter_scope()` push onto a stack for nested scope management?

3. Should scope tracking support glob patterns for filenames?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Scope Stack**: Push/pop scope for nested sandbox invocations with different configurations.

2. **Per-Scope Limits**: Different limits for different registered filenames.

3. ~~**Async Support**: Special handling for async generators and coroutines that may interleave.~~ **IMPLEMENTED**: Generator, coroutine, and async generator frame access (`gi_frame`, `cr_frame`, `ag_frame`) is blocked from sandbox scope to prevent information leakage. See "Security: Generator/Coroutine Frame Access" section above.

4. **Audit Logging**: Optional logging of all scope entries/exits for debugging.

5. **Recursion Depth Limit**: Add `max_recursion_depth` to sandbox limits to prevent interpreter crashes from deep recursion with exception re-raising.

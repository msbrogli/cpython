- Feature Name: sandbox-recursion
- Start Date: 2026-01-30
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox recursion module provides per-thread recursion depth tracking for sandboxed code. It counts the number of sandbox-scoped frames in the call stack and raises `SandboxRecursionError` when the configurable `max_recursion_depth` limit is exceeded. This prevents denial-of-service attacks through deep recursion that can crash the Python interpreter.

# Motivation
[motivation]: #motivation

Deep recursion in sandboxed code poses a critical security risk:

1. **Interpreter Crash (HYP-006)**: The security audit identified that deep recursion with exception re-raising can crash the Python interpreter with `Fatal Python error: _PyErr_NormalizeException: Cannot recover from the recursive normalization of an exception.`

2. **Stack Exhaustion**: Even without the exception normalization crash, deep recursion can exhaust the C stack, causing segmentation faults.

3. **Traceback Chain Growth**: Each level of recursion with exception handling can grow the traceback chain, consuming unbounded memory.

Python's built-in `sys.setrecursionlimit()` provides some protection, but:
- It's a global setting that affects all code, not just sandboxed code
- It doesn't distinguish between trusted and untrusted frames
- The default limit (1000) may be too high for some sandboxed use cases

The sandbox recursion limit addresses these issues by:
- Providing a sandbox-specific limit separate from Python's global limit
- Only counting sandbox-scoped frames (based on registered filenames)
- Raising a catchable `SandboxRecursionError` before the interpreter crashes

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Setting the Recursion Depth Limit

```python
import sys

# Set the maximum sandbox recursion depth
sys.sandbox.max_recursion_depth = 100

# Register filenames that should be subject to the limit
sys.sandbox.add_filename("<sandbox>")

# Execute untrusted code
code = compile(user_code, "<sandbox>", "exec")
try:
    exec(code)
except SandboxRecursionError as e:
    print(f"Recursion limit exceeded: {e}")
```

## How Depth is Counted

The recursion depth counts the **total number of sandbox-scoped frames** currently in the call stack. A frame is "in scope" if its `co_filename` is in the registered filenames set.

```python
# Example: Mixed scope calls
def trusted_helper():      # <main.py> - NOT in scope
    return sandbox_func()

def sandbox_func():        # <sandbox> - IN scope, depth += 1
    return another_func()

def another_func():        # <sandbox> - IN scope, depth += 1
    pass

# When sandbox_func calls another_func:
# - trusted_helper enters: depth = 0 (not in scope)
# - sandbox_func enters: depth = 1
# - another_func enters: depth = 2
```

## Generator Support

Generators correctly handle depth tracking across yield/resume:

```python
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename("<sandbox>")

code = '''
def gen():
    yield 1  # depth decrements on yield
    yield 2  # depth increments on resume, then decrements on yield
    yield 3

g = gen()
for value in g:  # Each iteration: resume (depth+1), yield (depth-1)
    print(value)
'''
exec(compile(code, "<sandbox>", "exec"))
```

## Catching the Exception

`SandboxRecursionError` is a subclass of `SandboxError` and can be caught:

```python
try:
    exec(untrusted_code)
except SandboxRecursionError:
    print("Recursion too deep - untrusted code may be malicious")
except SandboxError:
    print("Some other sandbox limit exceeded")
```

## Interaction with Python's Recursion Limit

The sandbox recursion limit is independent of Python's `sys.getrecursionlimit()`. Both limits can trigger:

- If sandbox limit triggers first: `SandboxRecursionError` is raised
- If Python limit triggers first: `RecursionError` is raised

For maximum protection, set the sandbox limit lower than Python's limit:

```python
import sys
sys.sandbox.max_recursion_depth = 100  # Sandbox limit
# Python's default is 1000
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

### Per-Thread Counter

A `uint64_t sandbox_recursion_depth` field is added to `PyThreadState` (`struct _ts` in `Include/cpython/pystate.h`). This counter tracks the current number of sandbox-scoped frames in the thread's call stack.

```c
struct _ts {
    // ... existing fields ...
    int recursion_headroom;

    /* Sandbox recursion depth: count of sandbox-scoped frames in call stack */
    uint64_t sandbox_recursion_depth;

    // ... rest of struct ...
};
```

### Limit Configuration

A `uint64_t max_recursion_depth` field is added to `_PySandboxLimits` (`Include/internal/pycore_sandbox.h`):

```c
typedef struct {
    // ... existing limits ...
    uint64_t max_operations;
    uint64_t max_recursion_depth;  /* 0 = no limit */
    // ... rest of struct ...
} _PySandboxLimits;
```

## Core Functions

### `_PySandbox_EnterFrame(frame)`

Called at frame entry (in `ceval.c` at `start_frame` label):

1. Fast-path exits if: suspended, suppress_checks, limit is 0, no registered filenames
2. Check if frame is in sandbox scope via `frame_in_sandbox_scope()`
3. If in scope, increment `tstate->sandbox_recursion_depth`
4. If depth exceeds limit, set `SandboxRecursionError` and return -1
5. Return 0 on success

### `_PySandbox_ExitFrame(frame)`

Called at frame exit (RETURN_VALUE, YIELD_VALUE, exit_unwind):

1. Fast-path exits matching EnterFrame conditions
2. Check if frame is in sandbox scope
3. If in scope and depth > 0, decrement `tstate->sandbox_recursion_depth`

## Hook Locations in ceval.c

```c
start_frame:
    if (_Py_EnterRecursiveCallTstate(tstate, "")) {
        tstate->recursion_remaining--;
        goto exit_unwind;
    }
    if (_PySandbox_EnterFrame(frame) < 0) {  // <-- NEW
        goto exit_unwind;
    }

// ... in RETURN_VALUE handler ...
    _PySandbox_ExitFrame(dying);  // Before _PyEvalFrameClearAndPop

// ... in YIELD_VALUE handler ...
    _PySandbox_ExitFrame(frame);  // Before returning

// ... in exit_unwind ...
    _PySandbox_ExitFrame(frame);  // Before returning/clearing
```

## Exception Type

`SandboxRecursionError` is added to the exception hierarchy:

```
Exception
└── SandboxError
    ├── SandboxOverflowError
    ├── SandboxMemoryError
    ├── SandboxRuntimeError
    ├── SandboxRecursionError  <- NEW
    ├── SandboxTypeError
    ├── SandboxAttributeError
    ├── SandboxSecurityError
    └── SandboxImportError
```

## Files Modified

| File | Changes |
|------|---------|
| `Include/cpython/pystate.h` | Add `sandbox_recursion_depth` to `struct _ts` |
| `Include/internal/pycore_sandbox.h` | Add `max_recursion_depth` to `_PySandboxLimits`, declare functions |
| `Include/pyerrors.h` | Add `PyExc_SandboxRecursionError` |
| `Objects/exceptions.c` | Define `SandboxRecursionError` |
| `Python/sandbox_recursion.c` | New file with `_PySandbox_EnterFrame`, `_PySandbox_ExitFrame` |
| `Python/sandbox_pyapi.c` | Add `max_recursion_depth` property |
| `Python/ceval.c` | Hook entry/exit points |
| `Makefile.pre.in` | Add `sandbox_recursion.o` |

# Drawbacks
[drawbacks]: #drawbacks

1. **Performance Overhead**: Every frame entry/exit in sandboxed code has additional function calls. The overhead is minimized by fast-path exits when the limit is 0 (default).

2. **Complexity**: Adding hooks in ceval.c increases the complexity of the interpreter loop. However, the hooks follow the same pattern as Python's existing recursion checking.

3. **Edge Cases**: The depth counter can underflow if `max_recursion_depth` is changed between frame entry and exit. The implementation handles this gracefully by not decrementing below 0.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Per-Thread Counter?

A per-thread counter (in `PyThreadState`) rather than a global counter ensures:
- Thread safety without locks
- Independent depth tracking per thread
- No race conditions in multi-threaded sandboxed code

## Why Frame-Based Counting?

Counting at frame entry/exit (rather than function calls or opcodes) provides:
- Deterministic behavior across platforms
- Correct handling of generators (yield decrements, resume increments)
- Clear semantic meaning (frames currently on stack)

## Alternative: Use Python's Recursion Limit

We could have modified `sys.setrecursionlimit()` to work with sandbox scope, but:
- It would break existing code that relies on the global limit
- It mixes trusted and untrusted frame counting
- It doesn't provide sandbox-specific error handling

## Alternative: Count All Frames

We could count all frames, not just sandbox-scoped ones, but:
- It would limit legitimate trusted helper functions
- It doesn't match the scope semantics of other sandbox limits
- Attackers could still exploit trusted code paths

# Prior art
[prior-art]: #prior-art

## Python's Built-in Recursion Limit

Python uses `sys.setrecursionlimit()` to prevent C stack overflow. Our implementation:
- Follows the same pattern (check at frame entry)
- Adds sandbox-scope awareness
- Uses a separate counter for independent control

## PyPy's Sandbox

PyPy's sandbox uses a similar approach with resource limits, though it operates at a lower level (operating system sandboxing). Our approach is pure Python/C and doesn't require OS support.

## JavaScript Engine Limits

V8 and SpiderMonkey have similar stack depth limits for script execution, though they typically operate on the C stack level rather than logical call frames.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. **Traceback Chain Limiting**: Should we also limit the depth of traceback chains separately? The recursion limit prevents the crash scenario, but very deep tracebacks from non-recursive code could still consume significant memory.

2. **Async/Await**: How should async coroutines interact with the depth limit? Currently, coroutines are handled the same as generators (via YIELD_VALUE), but there may be edge cases with deeply nested async calls.

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Traceback Depth Limit**: Add `max_traceback_depth` to limit exception traceback chain length as defense in depth.

2. **Call Graph Analysis**: Track not just depth but also call patterns to detect suspicious recursive behavior before hitting the limit.

3. **Per-Function Limits**: Allow setting different limits for specific functions within the sandbox.

4. **Memory-Based Limits**: Combine with memory tracking to limit total stack memory usage rather than just frame count.

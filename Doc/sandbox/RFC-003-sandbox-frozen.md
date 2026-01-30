- Feature Name: sandbox-frozen
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox frozen module provides attribute mutation control through two complementary mechanisms: global frozen mode (blocking all attribute mutations) and per-object freeze/mutable tracking. Auto-mutable mode automatically marks objects created within sandbox scope as mutable, allowing sandboxed code to modify its own objects while protecting shared state.

# Motivation
[motivation]: #motivation

Untrusted code can escape sandboxes or cause damage by modifying:

1. **Built-in Types**: `list.append = malicious_func`
2. **Module State**: `os.system = backdoor`
3. **Class Attributes**: `SomeClass.secret = exposed`

Frozen mode addresses this by blocking all attribute mutations within sandbox scope. However, sandboxed code legitimately needs to:

1. Create and modify its own classes
2. Set attributes on its own instances
3. Assign to local variables (module-level)

Auto-mutable mode solves this by automatically marking newly created objects as mutable, so sandboxed code can modify what it creates while being blocked from modifying pre-existing objects.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Global Frozen Mode

Enable frozen mode to block all attribute mutations:

```python
import sys

sys.sandbox.frozen_mode = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
class Foo:
    x = 1
Foo.x = 2  # Raises SandboxAttributeError
""", "<sandbox>", "exec")

try:
    exec(code)
except SandboxAttributeError as e:
    print(e)  # "cannot modify 'type' object: sandbox frozen mode is active"
```

## Per-Object Freezing

Freeze individual objects without enabling global frozen mode:

```python
import sys

class Config:
    debug = False

sys.sandbox.freeze(Config)

# Now Config is frozen
sys.sandbox.add_filename("<sandbox>")
code = compile("Config.debug = True", "<sandbox>", "exec")

try:
    exec(code, {"Config": Config})
except SandboxAttributeError as e:
    print(e)  # "cannot modify frozen object 'type'"
```

## Auto-Mutable Mode

Allow sandboxed code to modify objects it creates:

```python
import sys

sys.sandbox.frozen_mode = True
sys.sandbox.auto_mutable = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
class MyClass:
    x = 1

obj = MyClass()
MyClass.x = 2   # Allowed! MyClass is auto-marked mutable
obj.y = 3       # Allowed! obj is auto-marked mutable
""", "<sandbox>", "exec")

exec(code)  # Works without error
```

Without auto-mutable mode, the same code would fail on `MyClass.x = 2`.

## Priority Order

The mutation check follows this priority:

1. **Mutable set**: If object is in `mutable_objects` set, always allow
2. **Suspended**: If sandbox is suspended, allow
3. **Scope check**: Only block mutations from within sandbox scope
4. **Frozen set**: If object is in `frozen_objects` set, block
5. **Global frozen mode**: If active, block

```python
import sys

class SharedConfig:
    value = 1

class LocalConfig:
    value = 2

# SharedConfig is frozen, LocalConfig is mutable
sys.sandbox.freeze(SharedConfig)
sys.sandbox.set_mutable(LocalConfig)

sys.sandbox.frozen_mode = True
sys.sandbox.add_filename("<sandbox>")

code = compile("""
SharedConfig.value = 99  # Blocked (frozen)
LocalConfig.value = 99   # Allowed (mutable override)
""", "<sandbox>", "exec")
```

## Checking Object State

```python
sys.sandbox.is_frozen(obj)  # True if object is in frozen_objects set

# Note: There's no is_mutable() API; check via object inspection
# or trust that auto-mutable mode is handling it
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Side Tables for Frozen/Mutable Tracking

The implementation uses side tables (Python sets) stored in `_PySandboxState` rather than per-object flags. This avoids breaking ABI compatibility:

```c
typedef struct {
    // ... other sandbox fields ...

    /* Side tables for frozen mode (avoids per-object ob_flags ABI change).
     * mutable_objects: set of objects allowed to be mutated in frozen mode.
     * frozen_objects: set of individually frozen objects.
     * Uses weak references where possible, allowing tracked objects to be
     * garbage collected. Objects that don't support weak references (e.g.,
     * built-in type instances) fall back to strong references.
     * NULL when not in use (lazy-initialized). */
    PyObject *mutable_objects;
    PyObject *frozen_objects;

    // ... other fields ...
} _PySandboxState;
```

### Why Sets Instead of Per-Object Flags?

The side-table approach was chosen over per-object flags because:

1. **ABI Compatibility**: Adding fields to `PyObject` breaks binary compatibility with all existing C extensions, requiring full ecosystem recompilation.

2. **Sandbox-Specific**: Frozen/mutable tracking is only needed for sandbox functionality. Adding overhead to every Python object for a feature most users won't use is wasteful.

3. **Garbage Collection**: Using weak references where possible allows tracked objects to be garbage collected when no other references exist. This prevents memory leaks in long-running sandbox sessions.

### Weak Reference Implementation

Objects are tracked using weak references where possible:

```c
/* Add an object to a tracking set using weak references where possible. */
static int
add_to_weak_set(PyObject **setp, PyObject *obj)
{
    /* Lazy-init the set */
    if (*setp == NULL) {
        *setp = PySet_New(NULL);
        if (*setp == NULL) {
            return -1;
        }
    }

    /* Try to create a weak reference */
    PyObject *ref = PyWeakref_NewRef(obj, NULL);
    if (ref != NULL) {
        /* Object supports weak references - add the weakref */
        int rc = PySet_Add(*setp, ref);
        Py_DECREF(ref);
        return rc;
    }

    /* Object doesn't support weak references - use strong ref */
    PyErr_Clear();
    return PySet_Add(*setp, obj);
}
```

For membership checks, we create a temporary weak reference for comparison (weak references to the same object compare equal):

```c
static int
in_weak_set(PyObject *set, PyObject *obj)
{
    if (set == NULL) return 0;

    /* Try weak reference lookup first */
    PyObject *ref = PyWeakref_NewRef(obj, NULL);
    if (ref != NULL) {
        int result = PySet_Contains(set, ref);
        Py_DECREF(ref);
        if (result >= 0) return result;
        PyErr_Clear();
    } else {
        PyErr_Clear();
    }

    /* Fall back to direct lookup (for non-weakrefable objects) */
    return PySet_Contains(set, obj);
}
```

**Fallback behavior**: Objects that don't support weak references (e.g., instances of built-in types without `__weakref__` slot) are stored as strong references. This is a necessary trade-off since these objects cannot be weakly referenced.

## Frozen Check Function

```c
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    if (obj == NULL) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.suspended) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast path: check mutable set first */
    if (sandbox->mutable_objects != NULL) {
        int in_mutable = PySet_Contains(sandbox->mutable_objects, obj);
        if (in_mutable > 0) {
            return 0;  /* Allow - object is in mutable set */
        }
        if (in_mutable < 0) {
            PyErr_Clear();  /* Ignore lookup errors */
        }
    }

    /* Check if object is individually frozen */
    int is_frozen = 0;
    if (sandbox->frozen_objects != NULL) {
        int in_frozen = PySet_Contains(sandbox->frozen_objects, obj);
        if (in_frozen > 0) {
            is_frozen = 1;
        } else if (in_frozen < 0) {
            PyErr_Clear();
        }
    }

    /* Fast path: no frozen restrictions exist */
    if (!is_frozen && !sandbox->frozen_mode) {
        return 0;
    }

    /* Only enforce within sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope <= 0) {
        return 0;
    }

    if (is_frozen) {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify frozen object '%.100s'",
                     Py_TYPE(obj)->tp_name);
        return -1;
    }

    PyErr_Format(PyExc_SandboxAttributeError,
                 "cannot modify '%.100s' object: sandbox frozen mode is active",
                 Py_TYPE(obj)->tp_name);
    return -1;
}
```

## Auto-Mutable Implementation

```c
void
_PySandbox_MaybeMarkMutable(PyObject *obj)
{
    assert(obj != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }

    /* Fast path: both flags must be on */
    if (!interp->sandbox.auto_mutable || !interp->sandbox.frozen_mode) {
        return;
    }
    if (interp->sandbox.suspended) {
        return;
    }

    /* Check if current frame is in sandbox scope */
    _PySandboxState *sandbox = &interp->sandbox;
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope <= 0) {
        return;
    }

    /* Lazy-init the mutable set */
    if (sandbox->mutable_objects == NULL) {
        sandbox->mutable_objects = PySet_New(NULL);
        if (sandbox->mutable_objects == NULL) {
            PyErr_Clear();
            return;
        }
    }

    /* Add to mutable set */
    if (PySet_Add(sandbox->mutable_objects, obj) < 0) {
        PyErr_Clear();  /* Ignore errors (unhashable objects, etc.) */
    }
}
```

## C API

### Frozen Mode

```c
/* Enable/disable global frozen mode */
void PySandbox_SetFrozenMode(int mode);
int PySandbox_GetFrozenMode(void);

/* Per-object freeze (adds to frozen_objects set) */
void PySandbox_FreezeObject(PyObject *obj);
int PySandbox_IsObjectFrozen(PyObject *obj);

/* Mutable override (adds/removes from mutable_objects set) */
void PySandbox_SetObjectMutable(PyObject *obj, int mutable);
```

### Auto-Mutable Mode

```c
/* Enable/disable auto-mutable mode */
void PySandbox_SetAutoMutableMode(int mode);
int PySandbox_GetAutoMutableMode(void);

/* Called internally to auto-mark objects */
void _PySandbox_MaybeMarkMutable(PyObject *obj);
```

## Python API

### Properties

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `frozen_mode` | bool | False | Global attribute freeze |
| `auto_mutable` | bool | False | Auto-mark new objects as mutable |

### Methods

| Method | Description |
|--------|-------------|
| `freeze(obj)` | Add object to `frozen_objects` set |
| `is_frozen(obj)` | Check if object is in `frozen_objects` set |
| `set_mutable(obj, mutable=True)` | Add/remove object from `mutable_objects` set |

## Integration Points

`_PySandbox_CheckFrozen()` is called from:

| File | Function | Purpose |
|------|----------|---------|
| `Objects/object.c` | `PyObject_GenericSetAttr()` | Generic attribute set |
| `Objects/object.c` | `PyObject_GenericSetDict()` | `__dict__` assignment |
| `Objects/typeobject.c` | `type_setattro()` | Type attribute set |
| `Objects/descrobject.c` | descriptor `tp_descr_set` | Descriptor set/delete |

`_PySandbox_MaybeMarkMutable()` is called from:

| File | Function | Purpose |
|------|----------|---------|
| `Objects/typeobject.c` | `type_call()` | Mark new instances/classes |
| `Python/ceval.c` | `MAKE_FUNCTION` | Mark new function objects |

## Exception Type

All frozen mode violations raise `SandboxAttributeError`:

| Condition | Message |
|-----------|---------|
| Per-object frozen | `"cannot modify frozen object 'type'"` |
| Global frozen mode | `"cannot modify 'type' object: sandbox frozen mode is active"` |

# Drawbacks
[drawbacks]: #drawbacks

1. **Non-Weakrefable Objects**: Objects that don't support weak references (e.g., instances of many built-in types) are stored as strong references and will be kept alive until removed or sandbox is reset.

2. **Set Lookup Overhead**: Each mutation check requires a set lookup (O(1) average case) plus a weak reference creation for comparison. This is slower than per-object flags but avoids ABI breakage.

3. **Unhashable Objects**: Objects that are not hashable cannot be tracked. Errors are silently ignored.

4. **Dead Weak References**: When tracked objects are garbage collected, their weak references remain in the set until explicitly cleaned up or the sandbox is reset. This is minor overhead but not a memory leak.

5. **Performance Impact**: Every attribute mutation checks frozen mode, even when disabled (though fast-exit minimizes overhead).

6. **Incomplete Coverage**: Some mutation paths may not call `_PySandbox_CheckFrozen()` (C extensions, direct struct access).

7. **Auto-Mutable Scope**: Objects created by trusted code called from sandboxed code may be incorrectly marked mutable.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Side Tables vs. Per-Object Flags?

The chosen implementation uses side tables (Python sets) stored in interpreter state. This approach:

- **Preserves ABI**: No changes to `PyObject` structure
- **Lazy allocation**: Sets are only created when needed
- **Clean reset**: `sandbox.reset()` clears all tracking

### Alternative: Per-Object Flags (Rejected)

An alternative implementation would add flags directly to `PyObject`:

```c
typedef struct _object {
    Py_ssize_t ob_refcnt;
    uint32_t ob_flags;      /* Per-instance sandbox flags */
    PyTypeObject *ob_type;
} PyObject;

#define Py_OBJFLAGS_FROZEN    (1U << 0)
#define Py_OBJFLAGS_MUTABLE   (1U << 1)

#define Py_IS_FROZEN(op)  (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_FROZEN)
#define Py_IS_MUTABLE(op) (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_MUTABLE)
```

**Why this was rejected:**

1. **ABI Breaking Change**: Adding `ob_flags` to `PyObject` changes the memory layout of every Python object. This breaks binary compatibility with:
   - All compiled C extensions (numpy, pandas, etc.)
   - Cython-compiled modules
   - CFFI bindings
   - Any code that assumes `PyObject` size

2. **Ecosystem-Wide Recompilation**: All packages with C extensions would need to be recompiled. This is impractical for:
   - Production deployments
   - Users who can't rebuild packages
   - Binary wheels on PyPI

3. **Memory Overhead**: Adds 4 bytes to every Python object, even when sandbox is not used.

4. **Upstream Rejection Risk**: Changes to `PyObject` structure are extremely unlikely to be accepted upstream.

The side-table approach avoids all these issues while providing equivalent functionality.

## Why Both Global and Per-Object Modes?

- **Global mode**: Simple "freeze everything" for strict sandboxing
- **Per-object mode**: Fine-grained control for specific security needs

Both are useful; supporting both adds minimal complexity.

## Why Auto-Mutable?

Without auto-mutable, frozen mode would prevent sandboxed code from creating usable classes:

```python
# Without auto-mutable:
class Foo:
    pass
Foo.x = 1  # Error! Can't modify Foo
```

Auto-mutable solves this elegantly by marking `Foo` as mutable when it's created.

## Why Mark at Creation, Not First Mutation?

**Alternative**: Allow first mutation, then freeze.
- Rejected: Harder to implement; unclear semantics for "first"; potential race conditions.

# Prior art
[prior-art]: #prior-art

1. **JavaScript Object.freeze()**: Similar per-object freeze, but no auto-mutable equivalent.

2. **Python's __slots__**: Prevents adding new attributes, but doesn't block modification.

3. **Immutable.js**: Immutable data structures for JavaScript. Different approach (copy-on-write).

4. **Rust's ownership**: Compile-time mutation control. Stronger guarantees, but requires language support.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should there be an `is_mutable()` API to check the mutable flag?

2. Should frozen mode affect `__dict__` manipulation via `vars()`?

3. Should there be a way to "deep freeze" an object and its attributes?

4. Should WeakSets be used to avoid keeping tracked objects alive? (Current implementation accepts the trade-off for simplicity.)

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Transitive Freeze**: Freeze an object and all objects it references.

2. **Freeze Whitelist**: Allow specific attributes to remain mutable on frozen objects.

3. **Copy-on-Write**: Instead of blocking, create a copy when mutation is attempted.

4. **Audit Logging**: Log all mutation attempts on frozen objects.

5. **WeakSet Optimization**: Use WeakSets to allow garbage collection of tracked objects (requires callback mechanism to handle cleanup).

6. **Bloom Filter**: Add a "definitely not tracked" bloom filter to speed up the common case where objects are not in any set.

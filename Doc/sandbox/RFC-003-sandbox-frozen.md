- Feature Name: sandbox-frozen
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox frozen module provides attribute mutation control through two complementary mechanisms: global frozen mode (blocking all attribute mutations) and per-object freeze/mutable flags. Auto-mutable mode automatically marks objects created within sandbox scope as mutable, allowing sandboxed code to modify its own objects while protecting shared state.

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

1. **Mutable flag** (`Py_OBJFLAGS_MUTABLE`): If set, always allow
2. **Suspended**: If sandbox is suspended, allow
3. **Scope check**: Only block mutations from within sandbox scope
4. **Per-object frozen** (`Py_OBJFLAGS_FROZEN`): If set, block
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
sys.sandbox.is_frozen(obj)  # True if Py_OBJFLAGS_FROZEN is set

# Note: There's no is_mutable() API; check via object inspection
# or trust that auto-mutable mode is handling it
```

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Object Flags

Per-object flags are stored in `ob_flags` (added to `PyObject`):

```c
typedef struct _object {
    Py_ssize_t ob_refcnt;
    uint32_t ob_flags;      /* Per-instance sandbox flags */
    PyTypeObject *ob_type;
} PyObject;

#define Py_OBJFLAGS_FROZEN    (1U << 0)  /* Object is individually frozen */
#define Py_OBJFLAGS_MUTABLE   (1U << 1)  /* Override: allow mutation even in frozen mode */

#define Py_IS_FROZEN(op)  (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_FROZEN)
#define Py_IS_MUTABLE(op) (((PyObject*)(op))->ob_flags & Py_OBJFLAGS_MUTABLE)
```

## Frozen Check Function

```c
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* Fast path: mutable objects are always allowed */
    if (Py_IS_MUTABLE(obj)) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.suspended) {
        return 0;
    }

    int obj_frozen = Py_IS_FROZEN(obj);
    if (!obj_frozen && !interp->sandbox.frozen_mode) {
        return 0;  /* No frozen restrictions */
    }

    /* Only enforce within sandbox scope */
    _PySandboxState *sandbox = &interp->sandbox;
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return 0;
    }

    if (obj_frozen) {
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
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        return;
    }

    /* Mark the object as mutable */
    obj->ob_flags |= Py_OBJFLAGS_MUTABLE;
}
```

## C API

### Frozen Mode

```c
/* Enable/disable global frozen mode */
void PySandbox_SetFrozenMode(int mode);
int PySandbox_GetFrozenMode(void);

/* Per-object freeze */
void PySandbox_FreezeObject(PyObject *obj);
int PySandbox_IsObjectFrozen(PyObject *obj);

/* Mutable override */
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
| `freeze(obj)` | Set `Py_OBJFLAGS_FROZEN` on object |
| `is_frozen(obj)` | Check if object has `Py_OBJFLAGS_FROZEN` |
| `set_mutable(obj, mutable=True)` | Set/clear `Py_OBJFLAGS_MUTABLE` |

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

1. **Object Size Increase**: `ob_flags` adds 4 bytes to every Python object.

2. **Performance Impact**: Every attribute mutation checks frozen mode, even when disabled (though fast-exit minimizes overhead).

3. **Incomplete Coverage**: Some mutation paths may not call `_PySandbox_CheckFrozen()` (C extensions, direct struct access).

4. **Auto-Mutable Scope**: Objects created by trusted code called from sandboxed code may be incorrectly marked mutable.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Object Flags vs. Separate Registry?

**Alternative**: Maintain a separate `frozenset` of frozen object IDs.
- Rejected: O(1) flag check is faster than set lookup; no memory for registry.

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

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Transitive Freeze**: Freeze an object and all objects it references.

2. **Freeze Whitelist**: Allow specific attributes to remain mutable on frozen objects.

3. **Copy-on-Write**: Instead of blocking, create a copy when mutation is attempted.

4. **Audit Logging**: Log all mutation attempts on frozen objects.

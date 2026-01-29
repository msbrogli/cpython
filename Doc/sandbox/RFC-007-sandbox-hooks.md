- Feature Name: sandbox-hooks
- Start Date: 2025-01-29
- RFC PR: (leave this empty)
- Hathor Issue: (leave this empty)
- Author: Hathor Team

# Summary
[summary]: #summary

The sandbox hooks module provides object creation interception through a callback mechanism. When an object is created via `type_call()`, the registered hook is invoked with the new object, allowing monitoring, modification, or replacement of objects at creation time.

# Motivation
[motivation]: #motivation

Object creation hooks enable several use cases:

1. **Monitoring**: Track what types of objects sandboxed code creates
2. **Quotas**: Limit creation of specific object types
3. **Proxying**: Wrap created objects in proxies for further control
4. **Auditing**: Log object creation for security analysis
5. **Replacement**: Substitute objects with safe alternatives

While allocation counting limits total objects, creation hooks provide type-aware, fine-grained control over what gets created.

# Guide-level explanation
[guide-level-explanation]: #guide-level-explanation

## Setting a Creation Hook (Python)

```python
import sys

def my_hook(obj, type_, frame, context):
    """
    Called when an object is created via type_call().

    Args:
        obj: The newly created object
        type_: The type of the object (type(obj))
        frame: The current execution frame (or None)
        context: String describing the creation context

    Returns:
        The object to use (can return obj unchanged, or a replacement)
    """
    print(f"Created {type_.__name__}: {obj!r}")
    return obj  # Return the original object

sys.sandbox.creation_hook = my_hook

# Now object creation triggers the hook
class Foo:
    pass

instance = Foo()  # Prints: "Created Foo: <__main__.Foo object at 0x...>"
```

## Blocking Object Creation

Return `None` or raise an exception to block creation:

```python
import sys

def block_dangerous_types(obj, type_, frame, context):
    dangerous = {'subprocess.Popen', 'socket.socket'}
    full_name = f"{type_.__module__}.{type_.__name__}"

    if full_name in dangerous:
        raise SandboxTypeError(f"Creation of {full_name} is not allowed")

    return obj

sys.sandbox.creation_hook = block_dangerous_types
```

## Replacing Objects with Proxies

```python
import sys

class SafeList(list):
    """A list that limits its size."""
    def append(self, item):
        if len(self) >= 1000:
            raise SandboxOverflowError("List too large")
        super().append(item)

def proxy_lists(obj, type_, frame, context):
    if type_ is list:
        # Replace with SafeList
        safe = SafeList(obj)
        return safe
    return obj

sys.sandbox.creation_hook = proxy_lists

# Now list() returns SafeList
x = list()
print(type(x))  # <class 'SafeList'>
```

## Removing the Hook

```python
sys.sandbox.creation_hook = None
```

## Hook Context Values

The `context` parameter indicates how the object was created:

| Context | Description |
|---------|-------------|
| `"type_call"` | Created via `type.__call__()` (most common) |
| `"init"` | Created via `_PyObject_Init()` (C-level) |

# Reference-level explanation
[reference-level-explanation]: #reference-level-explanation

## Data Structures

```c
typedef PyObject* (*Py_ObjectCreationHookFunc)(
    PyObject *obj,          /* The object being created */
    PyTypeObject *type,     /* The type of the object */
    struct _frame *frame,   /* Current frame (may be NULL) */
    int flags,              /* Py_OBJHOOK_TYPE_CALL or Py_OBJHOOK_INIT */
    void *userdata          /* User-provided data pointer */
);

typedef struct {
    Py_ObjectCreationHookFunc hook_func;  /* C-level hook */
    void *hook_userdata;                   /* Userdata for C hook */
    PyObject *hook_callback;               /* Python-level callback */
    int in_hook;                           /* Recursion prevention */
} _PyObjectCreationHook;
```

## Hook Flags

```c
#define Py_OBJHOOK_TYPE_CALL  0x01  /* Called from type_call - can replace */
#define Py_OBJHOOK_INIT       0x02  /* Called from _PyObject_Init - observe only */
```

## Hook Invocation

Called from `Objects/typeobject.c` in `type_call()`:

```c
static PyObject *
type_call(PyTypeObject *type, PyObject *args, PyObject *kwds)
{
    PyObject *obj;

    /* Create the object */
    obj = type->tp_new(type, args, kwds);
    if (obj == NULL) {
        return NULL;
    }

    /* Call __init__ if needed */
    if (type->tp_init != NULL) {
        int res = type->tp_init(obj, args, kwds);
        if (res < 0) {
            Py_DECREF(obj);
            return NULL;
        }
    }

    /* Call creation hook - may replace obj */
    obj = _PySandbox_CallCreationHook(obj, type, Py_OBJHOOK_TYPE_CALL);
    if (obj == NULL) {
        return NULL;  /* Hook raised exception */
    }

    return obj;
}
```

## Creation Hook Implementation

```c
PyObject *
_PySandbox_CallCreationHook(PyObject *obj, PyTypeObject *type, int flags)
{
    if (obj == NULL) {
        return NULL;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return obj;
    }

    _PyObjectCreationHook *hook = &interp->sandbox.creation_hook;

    /* Recursion prevention */
    if (hook->in_hook) {
        return obj;
    }

    /* Check for Python callback */
    if (hook->hook_callback != NULL) {
        hook->in_hook = 1;

        /* Get current frame */
        PyThreadState *tstate = _PyThreadState_GET();
        PyObject *frame = NULL;
        if (tstate != NULL && tstate->cframe->current_frame != NULL) {
            frame = (PyObject *)PyFrame_GetFrameObject(
                tstate->cframe->current_frame);
        }

        /* Build context string */
        const char *context = (flags & Py_OBJHOOK_TYPE_CALL)
            ? "type_call" : "init";

        /* Call Python hook: hook(obj, type, frame, context) */
        PyObject *result = PyObject_CallFunction(
            hook->hook_callback, "OOOs",
            obj, (PyObject *)type, frame, context);

        Py_XDECREF(frame);
        hook->in_hook = 0;

        if (result == NULL) {
            Py_DECREF(obj);
            return NULL;  /* Hook raised exception */
        }

        if (result == Py_None) {
            Py_DECREF(result);
            Py_DECREF(obj);
            PyErr_SetString(PyExc_SandboxTypeError,
                            "Object creation blocked by hook");
            return NULL;
        }

        /* Replace obj with result */
        if (result != obj) {
            Py_DECREF(obj);
        }
        return result;
    }

    /* Check for C hook */
    if (hook->hook_func != NULL) {
        hook->in_hook = 1;

        PyFrameObject *frame = PyEval_GetFrame();
        PyObject *result = hook->hook_func(
            obj, type, frame, flags, hook->hook_userdata);

        hook->in_hook = 0;

        if (result == NULL) {
            Py_DECREF(obj);
            return NULL;
        }

        if (result != obj) {
            Py_DECREF(obj);
        }
        return result;
    }

    return obj;
}
```

## Recursion Prevention

The `in_hook` flag prevents infinite recursion when the hook itself creates objects:

```python
def my_hook(obj, type_, frame, context):
    log_entry = f"Created {type_.__name__}"  # Creates a string!
    # Without in_hook, this would trigger hook -> create string -> trigger hook -> ...
    return obj
```

## C API

```c
/* Set C-level creation hook */
void PySandbox_SetCreationHook(
    Py_ObjectCreationHookFunc hook,
    void *userdata);

/* Get C-level creation hook */
Py_ObjectCreationHookFunc PySandbox_GetCreationHook(void **userdata);

/* Internal: call the creation hook */
PyObject *_PySandbox_CallCreationHook(
    PyObject *obj,
    PyTypeObject *type,
    int flags);
```

## Python API

### Property

| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `creation_hook` | callable or None | None | Python creation hook callback |

### Hook Signature

```python
def creation_hook(
    obj: object,      # The newly created object
    type_: type,      # The type of the object
    frame: frame,     # Current execution frame (or None)
    context: str,     # "type_call" or "init"
) -> object:         # Return obj or replacement
    ...
```

### Return Values

| Return | Effect |
|--------|--------|
| `obj` (unchanged) | Object is used as-is |
| Different object | Replacement is used instead |
| `None` | Creation is blocked (`SandboxTypeError` raised) |
| Raises exception | Creation fails with that exception |

## When Hooks Are NOT Called

Creation hooks are only called from `type_call()`. They are NOT called for:

1. **C-level allocations**: `PyList_New()`, `PyDict_New()`, etc.
2. **Literals**: `[]`, `{}`, `""`, `123`
3. **Builtin operations**: `x + y` creating new object
4. **Special methods**: `__new__` returning cached object

This is by design: hooks are for monitoring/controlling user-level object creation, not internal Python operations.

# Drawbacks
[drawbacks]: #drawbacks

1. **Performance**: Hook invocation adds overhead to every `type_call()`.

2. **Limited Coverage**: Only covers `type_call()`, not C-level allocations.

3. **Recursion Complexity**: Hook must be careful not to trigger itself infinitely.

4. **Type Checking**: Returned replacement must be compatible with expected type.

5. **Reference Counting**: Hook must handle references correctly when replacing objects.

# Rationale and alternatives
[rationale-and-alternatives]: #rationale-and-alternatives

## Why Single Hook vs. Hook List?

**Alternative**: Allow multiple hooks
```python
sys.sandbox.add_creation_hook(hook1)
sys.sandbox.add_creation_hook(hook2)
```
- Rejected: Added complexity; unclear ordering; composition can be done in single hook.

## Why Return-Based Replacement vs. Mutation?

**Alternative**: Hook modifies object in-place
```python
def hook(obj, ...):
    obj.__sandbox_wrapped__ = True
    # No return needed
```
- Rejected: Can't replace with different type; less explicit control.

## Why Context String vs. Flag Enum?

**Alternative**: Use integer flags
```python
def hook(obj, type_, frame, flags):
    if flags & OBJHOOK_TYPE_CALL:
        ...
```
- Rejected: Less readable; string is self-documenting.

# Prior art
[prior-art]: #prior-art

1. **Python's `sys.settrace()`**: Function call/return tracing. Similar concept, different scope.

2. **`__new__` override**: Can intercept object creation, but per-class, not global.

3. **JavaScript Proxy**: Can intercept object operations including construction.

4. **Java JVMTI**: JVM Tool Interface allows object allocation callbacks.

# Unresolved questions
[unresolved-questions]: #unresolved-questions

1. Should hooks be called for C-level allocations?

2. Should there be a way to register type-specific hooks?

3. Should hook failures be recoverable (e.g., fallback to original object)?

# Future possibilities
[future-possibilities]: #future-possibilities

1. **Type-Specific Hooks**: Register hooks for specific types only.

2. **Allocation Hooks**: Extend to cover C-level allocations.

3. **Destruction Hooks**: Callback when objects are deallocated.

4. **Hook Chains**: Multiple hooks with defined ordering and short-circuit.

5. **Async Hook Support**: Hooks for async object creation patterns.

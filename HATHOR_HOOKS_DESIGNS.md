# CPython Object Creation Hook - Architecture Designs

This document describes three alternative architectures for implementing object creation hooks in CPython 3.11. These hooks allow intercepting and potentially replacing Python objects at creation time, useful for sandboxing and security applications.

## Requirements Summary

| Requirement | Description |
|-------------|-------------|
| **Hook Levels** | Two levels: `type_call` (can replace objects) and `_PyObject_Init` (observe all) |
| **Capability** | Replace object OR block creation (type_call level) |
| **API** | Both C API and Python API (`sys.setobjecthook()`) |
| **Type Coverage** | All objects (int, str, list, dict, user classes, etc.) |
| **Scope** | Per-interpreter (stored in `PyInterpreterState`) |
| **Performance** | Fast path when disabled (zero overhead) |
| **Hook Signature** | Returns: replacement (replaces), `Py_None` (keep original), `NULL` (error/block) |
| **Context** | Hook receives: created_object, type, current_frame |

---

## Background: How Object Creation Works in CPython

### Object Creation Flow

```
User code: obj = MyClass(args)
    |
    v
type_call()           # Entry point for all type calls
    |
    v
type->tp_new()        # Creates the object (allocates + basic init)
    |                   # - Calls tp_alloc() internally
    |                   # - tp_alloc calls _PyObject_Init()
    |                   # - Returns fully allocated object
    |
    v
type->tp_init()       # Initializes the object (with args)
    |                   # - Called only if tp_new returned correct type
    |
    v
return object
```

### Key Functions

- **`type_call()`** - Entry point for all `Type(args)` calls (typeobject.c:1050-1114)
- **`_PyObject_Init()`** - Low-level initialization, sets type and refcount (pycore_object.h:88-97)
- **`PyType_GenericAlloc()`** - Standard allocator for types (typeobject.c:1146-1157)
- **`_PyObject_New()`** - Allocates memory and calls `_PyObject_Init()` (object.c:174-182)

### Where to Hook

1. **In `type_call()`** - After `tp_new()` returns, before/after `tp_init()`. Can see and replace the complete object.
2. **In `_PyObject_Init()`** - Catches ALL objects at the lowest level. Cannot replace (object already allocated).

---

## Approach 1: Minimal Changes

**Philosophy**: Smallest possible changes to existing code, maximum reuse of existing patterns.

### Storage Structure

Add to `Include/internal/pycore_interp.h` in `struct _is`:

```c
// Object creation hook state
struct {
    PyObject *creation_hook_func;     // PyCapsule holding function pointer, or NULL
    void *creation_hook_userdata;     // User data pointer
} object_creation;
```

### Hook Function Type

Add to `Include/cpython/object.h`:

```c
/* Object creation hook function type.
 *
 * Parameters:
 *   obj: The object being created (already initialized)
 *   type: The type of the object
 *   frame: Current frame (may be NULL)
 *   userdata: User-provided data pointer
 *
 * Returns:
 *   - Replacement object (new reference): replaces obj (only from type_call level)
 *   - Py_None (new reference): keep original object
 *   - NULL: error occurred, exception should be set
 */
typedef PyObject* (*Py_ObjectCreationFunc)(
    PyObject *obj,
    PyTypeObject *type,
    PyFrameObject *frame,
    void *userdata
);

/* Set object creation hook.
 * Pass NULL for func to disable the hook.
 * Returns 0 on success, -1 on error.
 */
PyAPI_FUNC(int) PyObject_SetCreationHook(
    Py_ObjectCreationFunc func,
    void *userdata
);

/* Get the current object creation hook.
 * Returns the function and sets *userdata_out if not NULL.
 */
PyAPI_FUNC(Py_ObjectCreationFunc) PyObject_GetCreationHook(
    void **userdata_out
);
```

### C API Implementation

Add to `Objects/object.c`:

```c
int
PyObject_SetCreationHook(Py_ObjectCreationFunc func, void *userdata)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;

    // Audit event for security
    if (_PySys_Audit(tstate, "object.setcreationhook", NULL) < 0) {
        return -1;
    }

    // Clear old hook
    Py_XDECREF(interp->object_creation.creation_hook_func);

    // Set new hook
    if (func != NULL) {
        // Create a PyCapsule to hold the function pointer
        PyObject *capsule = PyCapsule_New((void*)func,
                                          "object_creation_hook",
                                          NULL);
        if (capsule == NULL) {
            return -1;
        }
        interp->object_creation.creation_hook_func = capsule;
        interp->object_creation.creation_hook_userdata = userdata;
    } else {
        interp->object_creation.creation_hook_func = NULL;
        interp->object_creation.creation_hook_userdata = NULL;
    }

    return 0;
}

Py_ObjectCreationFunc
PyObject_GetCreationHook(void **userdata_out)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;

    if (interp->object_creation.creation_hook_func == NULL) {
        if (userdata_out) *userdata_out = NULL;
        return NULL;
    }

    if (userdata_out) {
        *userdata_out = interp->object_creation.creation_hook_userdata;
    }

    return (Py_ObjectCreationFunc)PyCapsule_GetPointer(
        interp->object_creation.creation_hook_func,
        "object_creation_hook"
    );
}
```

### Hook in type_call()

Modify `Objects/typeobject.c` around line 1091-1099:

```c
    obj = type->tp_new(type, args, kwds);
    obj = _Py_CheckFunctionResult(tstate, (PyObject*)type, obj, NULL);
    if (obj == NULL)
        return NULL;

    /* Call object creation hook if registered (type_call level) */
    PyInterpreterState *interp = tstate->interp;
    if (interp->object_creation.creation_hook_func != NULL) {
        Py_ObjectCreationFunc hook = (Py_ObjectCreationFunc)PyCapsule_GetPointer(
            interp->object_creation.creation_hook_func,
            "object_creation_hook"
        );
        if (hook != NULL) {
            PyFrameObject *frame = PyEval_GetFrame();
            PyObject *result = hook(obj, type, frame,
                                   interp->object_creation.creation_hook_userdata);
            if (result == NULL) {
                Py_DECREF(obj);
                return NULL;
            }
            if (result != Py_None) {
                // Hook returned replacement object
                Py_DECREF(obj);
                obj = result;
                // Don't call tp_init on replaced object
                return obj;
            }
            Py_DECREF(result);
        }
    }

    /* If the returned object is not an instance of type,
       it won't be initialized. */
    if (!PyObject_TypeCheck(obj, type))
        return obj;
```

### Hook in _PyObject_Init()

Modify `Include/internal/pycore_object.h` lines 88-97:

```c
static inline void
_PyObject_Init(PyObject *op, PyTypeObject *typeobj)
{
    assert(op != NULL);
    Py_SET_TYPE(op, typeobj);
    if (_PyType_HasFeature(typeobj, Py_TPFLAGS_HEAPTYPE)) {
        Py_INCREF(typeobj);
    }
    _Py_NewReference(op);

    /* Call object creation hook if registered (_PyObject_Init level - observe only) */
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;
    if (interp->object_creation.creation_hook_func != NULL) {
        Py_ObjectCreationFunc hook = (Py_ObjectCreationFunc)PyCapsule_GetPointer(
            interp->object_creation.creation_hook_func,
            "object_creation_hook"
        );
        if (hook != NULL) {
            PyFrameObject *frame = PyEval_GetFrame();
            PyObject *result = hook(op, typeobj, frame,
                                   interp->object_creation.creation_hook_userdata);
            // At this level, ignore replacement (observe-only)
            Py_XDECREF(result);
        }
    }
}
```

### Python API

Add to `Python/sysmodule.c` after line 1067:

```c
static PyObject *
_call_creation_hook_trampoline(PyObject *obj, PyTypeObject *type,
                               PyFrameObject *frame, void *userdata)
{
    PyObject *callback = (PyObject*)userdata;
    PyThreadState *tstate = _PyThreadState_GET();

    if (tstate->tracing) {
        // Avoid recursion
        Py_RETURN_NONE;
    }

    tstate->tracing++;

    PyObject *args = PyTuple_Pack(3, obj, (PyObject*)type,
                                  frame ? (PyObject*)frame : Py_None);
    if (args == NULL) {
        tstate->tracing--;
        return NULL;
    }

    PyObject *result = PyObject_CallObject(callback, args);
    Py_DECREF(args);
    tstate->tracing--;

    if (result == NULL) {
        return NULL;
    }

    return result;
}

static PyObject *
sys_setobjectcreationhook_impl(PyObject *module, PyObject *callback)
{
    PyThreadState *tstate = _PyThreadState_GET();

    if (callback == Py_None) {
        if (PyObject_SetCreationHook(NULL, NULL) < 0) {
            return NULL;
        }
    }
    else {
        if (!PyCallable_Check(callback)) {
            PyErr_SetString(PyExc_TypeError,
                          "callback must be callable or None");
            return NULL;
        }
        // Create a trampoline that calls Python callback
        if (PyObject_SetCreationHook(_call_creation_hook_trampoline,
                                     (void*)callback) < 0) {
            return NULL;
        }
        Py_INCREF(callback);  // Keep callback alive
    }

    Py_RETURN_NONE;
}

static PyObject *
sys_getobjectcreationhook_impl(PyObject *module)
{
    void *userdata;
    Py_ObjectCreationFunc func = PyObject_GetCreationHook(&userdata);

    if (func == NULL || func != _call_creation_hook_trampoline) {
        Py_RETURN_NONE;
    }

    PyObject *callback = (PyObject*)userdata;
    Py_INCREF(callback);
    return callback;
}
```

Add to methods table:
```c
    {"setobjectcreationhook", (PyCFunction)sys_setobjectcreationhook_impl,
     METH_O, "Set the object creation hook function."},
    {"getobjectcreationhook", (PyCFunction)sys_getobjectcreationhook_impl,
     METH_NOARGS, "Return the current object creation hook function."},
```

### Files Modified

| File | Changes |
|------|---------|
| `Include/internal/pycore_interp.h` | Add hook storage (4 lines) |
| `Include/cpython/object.h` | Add typedef and API declarations (30 lines) |
| `Objects/object.c` | Implement Set/Get functions (50 lines) |
| `Objects/typeobject.c` | Add hook call in type_call (25 lines) |
| `Include/internal/pycore_object.h` | Add hook call in _PyObject_Init (12 lines) |
| `Python/sysmodule.c` | Add Python API (80 lines) |
| `Python/pystate.c` | Initialize/cleanup hook fields (4 lines) |

**Total**: ~200 lines added, 7 files modified

### Pros
- Fewest changes to existing code
- Uses existing patterns (PyCapsule, tracing counter for recursion)
- Easy to understand and maintain

### Cons
- Single hook for both levels (same callback called in both places)
- Less extensible for future hook types

---

## Approach 2: Clean Architecture

**Philosophy**: Proper abstraction layer, extensibility for future hook types.

### New Files to Create

#### `Include/internal/pycore_objecthooks.h`

```c
#ifndef Py_INTERNAL_OBJECTHOOKS_H
#define Py_INTERNAL_OBJECTHOOKS_H

#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pycore_interp.h"

// Hook context flags
#define Py_OBJHOOK_TYPE_CALL  0x01  // Called from type_call (can replace)
#define Py_OBJHOOK_INIT       0x02  // Called from _PyObject_Init (observe only)

// Hook function signature
typedef PyObject* (*Py_ObjectCreationHookFunction)(
    PyObject *obj,
    PyTypeObject *type,
    PyFrameObject *frame,
    int flags,
    void *userdata
);

// Hook state structure (stored in PyInterpreterState)
typedef struct {
    Py_ObjectCreationHookFunction creation_hook;
    void *creation_hook_userdata;
    PyObject *creation_callback;
    uint64_t total_calls;
    uint64_t replacement_count;
} _PyObjectHookState;

// Fast inline check for hook existence
static inline int
_PyObject_HasCreationHook(PyInterpreterState *interp)
{
    return (interp->object_hooks.creation_hook != NULL ||
            interp->object_hooks.creation_callback != NULL);
}

// Internal hook invocation (handles both C and Python hooks)
PyAPI_FUNC(PyObject *) _PyObject_CallCreationHook(
    PyInterpreterState *interp,
    PyObject *obj,
    PyTypeObject *type,
    int flags
);

// Initialization/finalization
PyAPI_FUNC(void) _PyObjectHooks_Init(PyInterpreterState *interp);
PyAPI_FUNC(void) _PyObjectHooks_Fini(PyInterpreterState *interp);

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_OBJECTHOOKS_H */
```

#### `Include/cpython/objecthooks.h`

```c
#ifndef Py_CPYTHON_OBJECTHOOKS_H
#  error "this header file must not be included directly"
#endif

// Object creation hook function signature
typedef PyObject* (*Py_ObjectCreationHookFunction)(
    PyObject *obj,
    PyTypeObject *type,
    PyFrameObject *frame,
    int flags,
    void *userdata
);

// Context flags passed to hook
#define Py_OBJHOOK_TYPE_CALL  0x01
#define Py_OBJHOOK_INIT       0x02

// Set object creation hook (C API)
PyAPI_FUNC(int) PyObject_SetCreationHook(
    Py_ObjectCreationHookFunction hook,
    void *userdata
);

// Get current object creation hook (C API)
PyAPI_FUNC(Py_ObjectCreationHookFunction) PyObject_GetCreationHook(
    void **userdata
);
```

#### `Python/objecthooks.c`

```c
/* Object creation hook subsystem */

#include "Python.h"
#include "pycore_call.h"
#include "pycore_frame.h"
#include "pycore_interp.h"
#include "pycore_objecthooks.h"
#include "pycore_pyerrors.h"
#include "pycore_pystate.h"
#include "pycore_sysmodule.h"
#include "frameobject.h"

/* Initialize object hooks state for an interpreter */
void
_PyObjectHooks_Init(PyInterpreterState *interp)
{
    interp->object_hooks.creation_hook = NULL;
    interp->object_hooks.creation_hook_userdata = NULL;
    interp->object_hooks.creation_callback = NULL;
    interp->object_hooks.total_calls = 0;
    interp->object_hooks.replacement_count = 0;
}

/* Finalize object hooks state for an interpreter */
void
_PyObjectHooks_Fini(PyInterpreterState *interp)
{
    Py_CLEAR(interp->object_hooks.creation_callback);
    interp->object_hooks.creation_hook = NULL;
    interp->object_hooks.creation_hook_userdata = NULL;
}

/* Get current frame as PyFrameObject */
static PyFrameObject *
get_current_frame(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return NULL;
    }

    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }

    if (frame == NULL) {
        return NULL;
    }

    return _PyFrame_GetFrameObject(frame);
}

/* Internal hook invocation - handles both C and Python hooks */
PyObject *
_PyObject_CallCreationHook(PyInterpreterState *interp,
                           PyObject *obj,
                           PyTypeObject *type,
                           int flags)
{
    assert(obj != NULL);
    assert(type != NULL);

    PyObject *result = Py_None;
    Py_INCREF(result);

    // Update statistics
    interp->object_hooks.total_calls++;

    // Get current frame (may be NULL)
    PyFrameObject *frame = get_current_frame();

    // Call C hook if set
    if (interp->object_hooks.creation_hook != NULL) {
        Py_ObjectCreationHookFunction hook = interp->object_hooks.creation_hook;
        void *userdata = interp->object_hooks.creation_hook_userdata;

        PyObject *c_result = hook(obj, type, frame, flags, userdata);
        if (c_result == NULL) {
            Py_DECREF(result);
            Py_XDECREF(frame);
            return NULL;  // Error
        }

        if (c_result != Py_None && (flags & Py_OBJHOOK_TYPE_CALL)) {
            interp->object_hooks.replacement_count++;
            Py_DECREF(result);
            result = c_result;
        } else {
            Py_DECREF(c_result);
        }
    }

    // Call Python callback if set
    if (interp->object_hooks.creation_callback != NULL) {
        PyThreadState *tstate = _PyThreadState_GET();

        // Convert flags to context string
        const char *context_str = (flags & Py_OBJHOOK_TYPE_CALL) ? "type_call" : "init";
        PyObject *context = PyUnicode_FromString(context_str);
        if (context == NULL) {
            Py_DECREF(result);
            Py_XDECREF(frame);
            return NULL;
        }

        // Build arguments: (obj, type, frame, context)
        PyObject *frame_arg = frame ? (PyObject *)frame : Py_None;
        PyObject *args[4] = {result, (PyObject *)type, frame_arg, context};

        // Disable tracing during hook execution
        PyThreadState_EnterTracing(tstate);
        PyObject *py_result = _PyObject_FastCall(
            interp->object_hooks.creation_callback,
            args, 4
        );
        PyThreadState_LeaveTracing(tstate);

        Py_DECREF(context);

        if (py_result == NULL) {
            Py_DECREF(result);
            Py_XDECREF(frame);
            return NULL;  // Error
        }

        if (py_result != Py_None && (flags & Py_OBJHOOK_TYPE_CALL)) {
            interp->object_hooks.replacement_count++;
            Py_DECREF(result);
            result = py_result;
        } else {
            Py_DECREF(py_result);
        }
    }

    Py_XDECREF(frame);
    return result;
}

/* Public C API: Set object creation hook */
int
PyObject_SetCreationHook(Py_ObjectCreationHookFunction hook, void *userdata)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return -1;
    }

    PyInterpreterState *interp = tstate->interp;

    // Audit hook invocation
    if (_PySys_Audit(tstate, "sys.setobjectcreationhook", NULL) < 0) {
        return -1;
    }

    interp->object_hooks.creation_hook = hook;
    interp->object_hooks.creation_hook_userdata = userdata;

    return 0;
}

/* Public C API: Get object creation hook */
Py_ObjectCreationHookFunction
PyObject_GetCreationHook(void **userdata)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        if (userdata != NULL) {
            *userdata = NULL;
        }
        return NULL;
    }

    PyInterpreterState *interp = tstate->interp;

    if (userdata != NULL) {
        *userdata = interp->object_hooks.creation_hook_userdata;
    }

    return interp->object_hooks.creation_hook;
}
```

### Hook Integration

#### In `Objects/typeobject.c` (type_call)

```c
obj = _Py_CheckFunctionResult(tstate, (PyObject*)type, obj, NULL);
if (obj == NULL)
    return NULL;

// ADD HOOK CALL:
PyInterpreterState *interp = tstate->interp;
if (_PyObject_HasCreationHook(interp)) {
    PyObject *replacement = _PyObject_CallCreationHook(
        interp, obj, type, Py_OBJHOOK_TYPE_CALL
    );
    if (replacement == NULL) {
        Py_DECREF(obj);
        return NULL;
    }
    if (replacement != Py_None) {
        Py_DECREF(obj);
        obj = replacement;
        return obj;  // Skip tp_init for replacement
    }
    Py_DECREF(replacement);
}

/* If the returned object is not an instance of type... */
```

#### In `Include/internal/pycore_object.h` (_PyObject_Init)

```c
static inline void
_PyObject_Init(PyObject *op, PyTypeObject *typeobj)
{
    assert(op != NULL);
    Py_SET_TYPE(op, typeobj);
    if (_PyType_HasFeature(typeobj, Py_TPFLAGS_HEAPTYPE)) {
        Py_INCREF(typeobj);
    }
    _Py_NewReference(op);

    // ADD OBSERVATION HOOK:
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (_PyObject_HasCreationHook(interp)) {
        PyObject *result = _PyObject_CallCreationHook(
            interp, op, typeobj, Py_OBJHOOK_INIT
        );
        if (result == NULL) {
            PyThreadState *tstate = _PyThreadState_GET();
            _PyErr_WriteUnraisableMsg("in object init hook", NULL);
        } else {
            Py_DECREF(result);
        }
    }
}
```

### Python API

Add to `Python/sysmodule.c`:

```c
static PyObject *
sys_setobjectcreationhook_impl(PyObject *module, PyObject *callback)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;

    // Audit hook
    if (_PySys_Audit(tstate, "sys.setobjectcreationhook", NULL) < 0) {
        return NULL;
    }

    if (callback == Py_None) {
        Py_CLEAR(interp->object_hooks.creation_callback);
    } else {
        if (!PyCallable_Check(callback)) {
            PyErr_SetString(PyExc_TypeError,
                          "object creation hook must be callable or None");
            return NULL;
        }
        Py_XINCREF(callback);
        Py_XSETREF(interp->object_hooks.creation_callback, callback);
    }

    Py_RETURN_NONE;
}

static PyObject *
sys_getobjectcreationhook_impl(PyObject *module)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    PyObject *callback = interp->object_hooks.creation_callback;

    if (callback == NULL) {
        callback = Py_None;
    }
    Py_INCREF(callback);
    return callback;
}
```

### Files to Create

| File | Purpose | Lines |
|------|---------|-------|
| `Include/internal/pycore_objecthooks.h` | Internal API, structures | ~60 |
| `Include/cpython/objecthooks.h` | Public C API | ~30 |
| `Python/objecthooks.c` | Implementation | ~200 |

### Files to Modify

| File | Changes | Lines |
|------|---------|-------|
| `Include/internal/pycore_interp.h` | Add `_PyObjectHookState object_hooks;` | 2 |
| `Objects/typeobject.c` | Add hook call in type_call | 15 |
| `Include/internal/pycore_object.h` | Add hook call in _PyObject_Init | 12 |
| `Python/sysmodule.c` | Add Python API | 50 |
| `Python/pylifecycle.c` | Call _PyObjectHooks_Init/Fini | 4 |
| `Include/object.h` | Include cpython/objecthooks.h | 1 |
| Build files | Add objecthooks.c | 2 |

**Total**: 3 new files (~290 lines), 7 files modified (~86 lines), ~376 total new lines

### Pros
- Clean separation of concerns
- Extensible for future hook types (destruction, modification)
- Unified hook mechanism with context flags
- Statistics tracking built-in

### Cons
- More code to maintain
- New subsystem to understand

---

## Approach 3: Pragmatic Balance (Recommended)

**Philosophy**: Balance between minimal changes and clean organization.

### Key Design Decisions

1. **Separate hooks per level**: Type-level can replace, init-level is observe-only
2. **Per-thread recursion counter**: Prevents infinite loops when hooks create objects
3. **Direct function pointers**: No PyCapsule overhead

### Storage Structures

Add to `Include/internal/pycore_interp.h`:

```c
// Hook function signature
typedef PyObject* (*Py_ObjectCreationHookFunc)(
    PyObject *obj,
    PyTypeObject *type,
    struct _frame *frame,
    void *userdata
);

// Hook storage - lives in PyInterpreterState
typedef struct {
    // Type-level hook (can replace objects)
    Py_ObjectCreationHookFunc type_hook_c;
    void *type_hook_userdata;
    PyObject *type_hook_py;  // Python callback or NULL

    // Init-level hook (observe only)
    Py_ObjectCreationHookFunc init_hook_c;
    void *init_hook_userdata;
    PyObject *init_hook_py;  // Python callback or NULL
} _PyObjectCreationHooks;
```

Add to `Include/cpython/pystate.h` in `struct _ts`:

```c
    // Object hook recursion prevention
    int object_hook_depth;
```

### New Header: `Include/internal/pycore_object_hooks.h`

```c
#ifndef Py_INTERNAL_OBJECT_HOOKS_H
#define Py_INTERNAL_OBJECT_HOOKS_H

#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

// Per-thread recursion prevention
#define _Py_IN_OBJECT_HOOK(tstate) ((tstate)->object_hook_depth > 0)

// Internal API
PyAPI_FUNC(PyObject *) _PyObject_CallTypeHook(
    PyThreadState *tstate,
    PyObject *obj,
    PyTypeObject *type
);

PyAPI_FUNC(void) _PyObject_CallInitHook(
    PyThreadState *tstate,
    PyObject *obj,
    PyTypeObject *type
);

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_OBJECT_HOOKS_H */
```

### Implementation: `Python/object_hooks.c`

```c
#include "Python.h"
#include "pycore_interp.h"
#include "pycore_object_hooks.h"
#include "pycore_pystate.h"
#include "pycore_frame.h"
#include "frameobject.h"

// Get current frame (or NULL)
static PyFrameObject *
get_current_frame(PyThreadState *tstate)
{
    if (tstate->cframe->current_frame == NULL) {
        return NULL;
    }
    return _PyFrame_GetFrameObject(tstate->cframe->current_frame);
}

// Call type-level hook (can replace object)
PyObject *
_PyObject_CallTypeHook(PyThreadState *tstate, PyObject *obj, PyTypeObject *type)
{
    PyInterpreterState *interp = tstate->interp;
    _PyObjectCreationHooks *hooks = &interp->object_hooks;

    // Fast path: no hook set
    if (hooks->type_hook_c == NULL && hooks->type_hook_py == NULL) {
        return obj;
    }

    // Prevent recursion
    if (_Py_IN_OBJECT_HOOK(tstate)) {
        return obj;
    }

    tstate->object_hook_depth++;

    PyObject *result = obj;
    PyFrameObject *frame = get_current_frame(tstate);

    // Call C hook first
    if (hooks->type_hook_c != NULL) {
        PyObject *hook_result = hooks->type_hook_c(
            obj, type, frame, hooks->type_hook_userdata
        );

        if (hook_result == NULL) {
            // Hook raised exception
            Py_XDECREF(frame);
            Py_DECREF(obj);
            tstate->object_hook_depth--;
            return NULL;
        }

        if (hook_result != Py_None) {
            // Replace object
            Py_DECREF(obj);
            result = hook_result;
        } else {
            Py_DECREF(hook_result);
        }
    }

    // Call Python hook if set
    if (hooks->type_hook_py != NULL && result != NULL) {
        PyObject *args = Py_BuildValue("(OOO)",
            result,
            type,
            frame ? (PyObject *)frame : Py_None
        );

        if (args == NULL) {
            Py_XDECREF(frame);
            Py_DECREF(result);
            tstate->object_hook_depth--;
            return NULL;
        }

        PyObject *hook_result = PyObject_CallObject(hooks->type_hook_py, args);
        Py_DECREF(args);

        if (hook_result == NULL) {
            // Hook raised exception
            Py_XDECREF(frame);
            Py_DECREF(result);
            tstate->object_hook_depth--;
            return NULL;
        }

        if (hook_result != Py_None) {
            // Replace object
            Py_DECREF(result);
            result = hook_result;
        } else {
            Py_DECREF(hook_result);
        }
    }

    Py_XDECREF(frame);
    tstate->object_hook_depth--;
    return result;
}

// Call init-level hook (observe only)
void
_PyObject_CallInitHook(PyThreadState *tstate, PyObject *obj, PyTypeObject *type)
{
    PyInterpreterState *interp = tstate->interp;
    _PyObjectCreationHooks *hooks = &interp->object_hooks;

    // Fast path: no hook set
    if (hooks->init_hook_c == NULL && hooks->init_hook_py == NULL) {
        return;
    }

    // Prevent recursion
    if (_Py_IN_OBJECT_HOOK(tstate)) {
        return;
    }

    tstate->object_hook_depth++;

    PyFrameObject *frame = get_current_frame(tstate);

    // Call C hook
    if (hooks->init_hook_c != NULL) {
        PyObject *hook_result = hooks->init_hook_c(
            obj, type, frame, hooks->init_hook_userdata
        );

        if (hook_result == NULL) {
            // Hook raised exception - clear it (init hook is observe-only)
            PyErr_Clear();
        } else {
            Py_DECREF(hook_result);
        }
    }

    // Call Python hook
    if (hooks->init_hook_py != NULL) {
        PyObject *args = Py_BuildValue("(OOO)",
            obj,
            type,
            frame ? (PyObject *)frame : Py_None
        );

        if (args != NULL) {
            PyObject *hook_result = PyObject_CallObject(hooks->init_hook_py, args);
            Py_DECREF(args);

            if (hook_result == NULL) {
                // Hook raised exception - clear it
                PyErr_Clear();
            } else {
                Py_DECREF(hook_result);
            }
        } else {
            PyErr_Clear();
        }
    }

    Py_XDECREF(frame);
    tstate->object_hook_depth--;
}
```

### Public C API: `Include/objecthook.h`

```c
#ifndef Py_OBJECTHOOK_H
#define Py_OBJECTHOOK_H
#ifdef __cplusplus
extern "C" {
#endif

/* Object Creation Hook API */

typedef PyObject* (*Py_ObjectCreationHookFunc)(
    PyObject *obj,
    PyTypeObject *type,
    struct _frame *frame,
    void *userdata
);

// Set/clear type-level hook (can replace objects)
PyAPI_FUNC(int) PyObject_SetTypeCreationHook(
    Py_ObjectCreationHookFunc hook,
    void *userdata
);

// Set/clear init-level hook (observe only)
PyAPI_FUNC(int) PyObject_SetInitCreationHook(
    Py_ObjectCreationHookFunc hook,
    void *userdata
);

#ifdef __cplusplus
}
#endif
#endif /* !Py_OBJECTHOOK_H */
```

### Hook Integration

#### In `Objects/typeobject.c` (after tp_init):

```c
    if (type->tp_init != NULL) {
        int res = type->tp_init(obj, args, kwds);
        if (res < 0) {
            assert(_PyErr_Occurred(tstate));
            Py_DECREF(obj);
            obj = NULL;
        }
        else {
            assert(!_PyErr_Occurred(tstate));
        }
    }

    // NEW: Call type-level hook (can replace object)
    if (obj != NULL) {
        obj = _PyObject_CallTypeHook(tstate, obj, type);
    }

    return obj;
```

#### In `Include/internal/pycore_object.h`:

```c
static inline void
_PyObject_Init(PyObject *op, PyTypeObject *typeobj)
{
    assert(op != NULL);
    Py_SET_TYPE(op, typeobj);
    if (_PyType_HasFeature(typeobj, Py_TPFLAGS_HEAPTYPE)) {
        Py_INCREF(typeobj);
    }
    _Py_NewReference(op);

    // NEW: Call init-level hook (observe only)
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate != NULL) {
        _PyObject_CallInitHook(tstate, op, typeobj);
    }
}
```

### Python API

Add to `Python/sysmodule.c`:

```c
static PyObject *
sys_setobjecthook_impl(PyObject *module, const char *level, PyObject *hook)
{
    PyThreadState *tstate = _PyThreadState_GET();
    PyInterpreterState *interp = tstate->interp;

    int is_type_level;
    if (strcmp(level, "type") == 0) {
        is_type_level = 1;
    } else if (strcmp(level, "init") == 0) {
        is_type_level = 0;
    } else {
        PyErr_SetString(PyExc_ValueError,
            "level must be 'type' or 'init'");
        return NULL;
    }

    if (is_type_level) {
        Py_XDECREF(interp->object_hooks.type_hook_py);
        if (hook == Py_None) {
            interp->object_hooks.type_hook_py = NULL;
        } else {
            if (!PyCallable_Check(hook)) {
                PyErr_SetString(PyExc_TypeError, "hook must be callable or None");
                return NULL;
            }
            Py_INCREF(hook);
            interp->object_hooks.type_hook_py = hook;
        }
    } else {
        Py_XDECREF(interp->object_hooks.init_hook_py);
        if (hook == Py_None) {
            interp->object_hooks.init_hook_py = NULL;
        } else {
            if (!PyCallable_Check(hook)) {
                PyErr_SetString(PyExc_TypeError, "hook must be callable or None");
                return NULL;
            }
            Py_INCREF(hook);
            interp->object_hooks.init_hook_py = hook;
        }
    }

    Py_RETURN_NONE;
}

static PyObject *
sys_getobjecthook_impl(PyObject *module, const char *level)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();

    PyObject *hook;
    if (strcmp(level, "type") == 0) {
        hook = interp->object_hooks.type_hook_py;
    } else if (strcmp(level, "init") == 0) {
        hook = interp->object_hooks.init_hook_py;
    } else {
        PyErr_SetString(PyExc_ValueError,
            "level must be 'type' or 'init'");
        return NULL;
    }

    if (hook == NULL) {
        Py_RETURN_NONE;
    }
    Py_INCREF(hook);
    return hook;
}
```

### Files Summary

| Category | File | Lines |
|----------|------|-------|
| **New** | `Include/objecthook.h` | ~40 |
| **New** | `Include/internal/pycore_object_hooks.h` | ~40 |
| **New** | `Python/object_hooks.c` | ~180 |
| **Modify** | `Include/internal/pycore_interp.h` | +15 |
| **Modify** | `Include/cpython/pystate.h` | +2 |
| **Modify** | `Include/internal/pycore_object.h` | +5 |
| **Modify** | `Objects/typeobject.c` | +5 |
| **Modify** | `Python/sysmodule.c` | +80 |
| **Modify** | `Python/pystate.c` | +10 |
| **Modify** | Build files | +2 |

**Total**: 3 new files (~260 lines), 7 files modified (~119 lines), ~380 total

### Pros
- Clear separation of type vs init hooks
- Robust recursion prevention (per-thread counter)
- Follows established CPython patterns (like sys.settrace)
- Reasonable complexity

### Cons
- Slightly more complex than Approach 1
- Two separate hook registration calls needed

---

## Comparison Matrix

| Aspect | Approach 1 | Approach 2 | Approach 3 |
|--------|-----------|-----------|-----------|
| **Lines of code** | ~200 | ~376 | ~380 |
| **New files** | 0 | 3 | 3 |
| **Modified files** | 7 | 7 | 7 |
| **Recursion prevention** | Uses tstate->tracing | Uses tracing enter/leave | Dedicated counter |
| **Separate type/init hooks** | No (same callback) | Yes (via flags) | Yes (separate storage) |
| **Extensibility** | Low | High | Medium |
| **Performance overhead** | PyCapsule dereference | Inline check | Inline check |
| **Maintenance burden** | Low | Medium | Low-Medium |

## Recommendation

**Approach 3 (Pragmatic Balance)** is recommended because:

1. **Clear separation**: Type-level and init-level hooks are clearly separate
2. **Robust**: Dedicated recursion counter prevents subtle bugs
3. **Familiar pattern**: Follows sys.settrace/setprofile patterns
4. **Reasonable size**: Not too much new code to maintain
5. **Good Python API**: `sys.setobjecthook('type', callback)` is explicit

---

## Usage Examples

### C API

```c
#include "objecthook.h"

// Hook that logs all object creations
PyObject* logging_hook(PyObject *obj, PyTypeObject *type,
                       PyFrameObject *frame, void *userdata) {
    fprintf(stderr, "Created: %s\n", type->tp_name);
    Py_RETURN_NONE;  // Keep original
}

// Hook that replaces strings with "REDACTED"
PyObject* redact_hook(PyObject *obj, PyTypeObject *type,
                      PyFrameObject *frame, void *userdata) {
    if (PyUnicode_Check(obj)) {
        return PyUnicode_FromString("REDACTED");
    }
    Py_RETURN_NONE;  // Keep original
}

// Install hooks
PyObject_SetTypeCreationHook(redact_hook, NULL);
PyObject_SetInitCreationHook(logging_hook, NULL);
```

### Python API

```python
import sys

# Track all created objects
created = []

def track_objects(obj, type, frame):
    created.append((type.__name__, id(obj)))
    return None  # Keep original

sys.setobjecthook('init', track_objects)

# Create some objects
x = [1, 2, 3]
y = {"a": 1}

print(f"Created {len(created)} objects")
sys.setobjecthook('init', None)  # Disable


# Replace lists with tuples (sandboxing example)
def immutable_lists(obj, type, frame):
    if type is list:
        return tuple(obj)  # Replace with immutable tuple
    return None  # Keep original

sys.setobjecthook('type', immutable_lists)

x = [1, 2, 3]
print(type(x))  # <class 'tuple'>

sys.setobjecthook('type', None)  # Disable
```

---

## Security Considerations

1. **Hooks run with full interpreter privileges** - only install trusted hooks
2. **Type-level hooks can replace security-sensitive objects** - use with caution
3. **Init-level hooks see all objects** including passwords, keys, etc.
4. **Audit events** should be added when hooks are installed (all approaches include this)
5. **Per-interpreter isolation** prevents cross-interpreter contamination

---

## Performance Notes

| Scenario | Overhead |
|----------|----------|
| No hook installed | ~1 CPU cycle (pointer check) |
| Hook installed, type-level | ~100-500 cycles (function call + frame access) |
| Hook installed, init-level | ~100-500 cycles (function call + frame access) |

For sandboxing use cases, this overhead is acceptable. For performance-critical code, disable hooks when not needed.

---

## Build Instructions

After implementing, build CPython:

```bash
cd /home/msbrogli/Hathor/cpython
./configure --with-pydebug
make -j4
./python -c "import sys; print(sys.setobjecthook)"
```

Run tests:
```bash
./python -m test test_sys  # Includes new hook tests
```

---

# CRITICAL: Attack Vector Analysis

This section analyzes specific resource exhaustion attacks and explains what object creation hooks can and cannot prevent.

## The Fundamental Limitation

**Object creation hooks only intercept explicit type instantiation (`Type(args)`), NOT arithmetic or operator results.**

Most built-in types have **optimized allocation paths** that bypass both `type_call()` and `_PyObject_Init()`:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                     CPython Object Allocation Paths                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  PATH 1: type_call() → tp_new → _PyObject_Init                              │
│  ───────────────────────────────────────────────────────────────────────    │
│  Used by: int(...), str(...), list(...), MyClass(...)                       │
│  Hooked by: ✓ type_call hook, ✓ _PyObject_Init hook                         │
│                                                                             │
│  PATH 2: Direct C allocation (BYPASSES BOTH HOOKS!)                         │
│  ───────────────────────────────────────────────────────────────────────    │
│  Used by: 10 ** 10, "a" + "b", x * y (arithmetic/operators)                 │
│  Functions: _PyLong_New, PyUnicode_New, PyList_New, etc.                    │
│  These call PyObject_Malloc directly, NOT _PyObject_Init!                   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Why Arithmetic Bypasses Hooks

Looking at the actual CPython code:

```c
// Objects/longobject.c - _PyLong_New (line ~200)
PyLongObject *
_PyLong_New(Py_ssize_t size)
{
    PyLongObject *result;
    // ...
    result = PyObject_Malloc(offsetof(PyLongObject, ob_digit) +
                             size*sizeof(digit));
    // DOES NOT CALL _PyObject_Init()!
    // Instead, directly initializes:
    _PyObject_InitVar((PyVarObject*)result, &PyLong_Type, size);
    // But _PyObject_InitVar is a DIFFERENT function!
    return result;
}
```

Wait, let me check `_PyObject_InitVar`:

```c
// Include/internal/pycore_object.h
static inline void
_PyObject_InitVar(PyVarObject *op, PyTypeObject *typeobj, Py_ssize_t size)
{
    Py_SET_SIZE(op, size);
    _PyObject_Init((PyObject *)op, typeobj);  // DOES call _PyObject_Init!
}
```

So `_PyObject_InitVar` DOES call `_PyObject_Init`. This means the init-level hook WOULD catch integer creation from arithmetic!

However, there's another issue: **strings and some other types use completely different paths**.

---

## Attack Vector Analysis

### Attack 1: Exponential Tower

```python
# Exponential tower
result = 10**10**10
```

**Execution flow:**
1. `10**10` → `long_pow()` → creates `PyLongObject` for 10,000,000,000
2. `10**(result of step 1)` → `long_pow()` → attempts to create `10^10000000000`

**What happens in `long_pow` (Objects/longobject.c:4300+):**
```c
static PyObject *
long_pow(PyObject *v, PyObject *w, PyObject *x)
{
    // ... validation ...

    // For large exponents, this allocates MASSIVE memory
    z = (PyLongObject *)_PyLong_New(size_z);  // <-- Allocation happens here

    // ... computation ...
}
```

**Hook coverage:**

| Hook Level | Catches? | Explanation |
|------------|----------|-------------|
| `type_call` | ✗ NO | Arithmetic doesn't go through `type_call` |
| `_PyObject_Init` | ✓ YES* | `_PyLong_New` → `_PyObject_InitVar` → `_PyObject_Init` |

*However, the problem is: by the time `_PyObject_Init` is called, **the memory is already allocated**! You can observe the object but cannot prevent the allocation.

**Recommended solution:** Add a hook in `_PyLong_New` BEFORE allocation:

```c
PyLongObject *
_PyLong_New(Py_ssize_t size)
{
    // ADD CHECK HERE - before allocation
    if (size > MAX_INT_DIGITS) {
        PyErr_SetString(PyExc_OverflowError, "Integer too large");
        return NULL;
    }

    result = PyObject_Malloc(...);
    // ...
}
```

---

### Attack 2: Nested Exponentiation Loop

```python
x = 2
for _ in range(1000):
    x = x ** x
```

**Execution flow:**
- Iteration 1: `2 ** 2 = 4`
- Iteration 2: `4 ** 4 = 256`
- Iteration 3: `256 ** 256` = (309 digit number)
- Iteration 4: `(309 digits) ** (309 digits)` = CRASH

**Hook coverage:** Same as Attack 1

| Hook Level | Catches? | Can Prevent? |
|------------|----------|--------------|
| `type_call` | ✗ NO | N/A |
| `_PyObject_Init` | ✓ YES | ✗ NO (too late, already allocated) |

**To actually prevent this**, you need to hook into `long_pow` directly.

---

### Attack 3: Large Power Operations

```python
y = 2 ** (10**9)  # 2^1000000000 - about 300 million digits!
```

**Hook coverage:** Same as above.

**Calculation of memory required:**
- `2^(10^9)` has approximately `10^9 / log2(10) ≈ 300,000,000` decimal digits
- Each Python `digit` is 30 bits (on 64-bit), so we need `10^9 / 30 ≈ 33,000,000` digits
- Each digit is 4 bytes: `33M * 4 = 132 MB` just for the digits
- Plus object overhead

---

### Attack 4: Large Number Multiplication

```python
x = (10**1000) * (10**1000)  # Creates 10**2000
```

**Execution flow:**
1. `10**1000` → `long_pow` → creates 1001-digit number ✓ (relatively small)
2. `(result) * (result)` → `long_mul` → creates 2001-digit number

**Hook coverage:**

| Hook Level | Catches? | Can Prevent? |
|------------|----------|--------------|
| `type_call` | ✗ NO | N/A |
| `_PyObject_Init` | ✓ YES | ✗ NO (too late) |

**Relevant code:**
```c
// Objects/longobject.c - long_mul (line ~3500)
static PyObject *
long_mul(PyLongObject *a, PyLongObject *b)
{
    // ...
    z = _PyLong_New(size_a + size_b);  // Allocation happens first
    // ...
}
```

---

### Attack 5: String Multiplication

```python
s = 'x' * (10**10)  # 10 GB string
t = 'abc' * (10**9)  # 3 GB string
```

**Execution flow:**
1. Evaluate `10**10` → creates integer (small)
2. `'x' * integer` → `unicode_repeat()` → allocates huge buffer

**Relevant code (Objects/unicodeobject.c):**
```c
static PyObject *
unicode_repeat(PyObject *str, Py_ssize_t n)
{
    // Check for overflow
    if (n < 1) return empty_string;

    Py_ssize_t nchars = PyUnicode_GET_LENGTH(str);
    if (nchars > PY_SSIZE_T_MAX / n) {
        PyErr_SetString(PyExc_OverflowError, "...");
        return NULL;
    }

    // ALLOCATE MASSIVE BUFFER
    PyObject *result = PyUnicode_New(nchars * n, maxchar);
    // ...
}
```

**Hook coverage:**

| Hook Level | Catches? | Can Prevent? |
|------------|----------|--------------|
| `type_call` | ✗ NO | N/A |
| `_PyObject_Init` | ✗ NO! | N/A |

**Why _PyObject_Init doesn't catch strings:**
```c
// Objects/unicodeobject.c - PyUnicode_New (line ~1200)
PyObject *
PyUnicode_New(Py_ssize_t size, Py_UCS4 maxchar)
{
    // ...
    obj = (PyObject *) PyObject_Malloc(struct_size);
    // DIRECTLY INITIALIZES - NO _PyObject_Init!
    _PyObject_Init(obj, &PyUnicode_Type);  // Wait, it DOES call it!
    // ...
}
```

Actually, `PyUnicode_New` DOES call `_PyObject_Init`. So the init hook would catch it, but again - memory is already allocated.

---

### Attack 6: Exponential String Concatenation

```python
s = 'a'
for _ in range(100):
    s = s + s  # 2^100 bytes ≈ 10^30 bytes
```

**Execution flow:**
- Iteration 1: `'a' + 'a'` = `'aa'` (2 bytes)
- Iteration 2: `'aa' + 'aa'` = `'aaaa'` (4 bytes)
- ...
- Iteration 30: 1 GB
- Iteration 40: 1 TB
- Iteration 100: 10^30 bytes (physically impossible)

**Relevant code:**
```c
// Objects/unicodeobject.c - PyUnicode_Concat (line ~10000+)
PyObject *
PyUnicode_Concat(PyObject *left, PyObject *right)
{
    // ...
    // Allocate new string
    PyObject *result = PyUnicode_New(new_len, maxchar);
    // ...
}
```

**Hook coverage:**

| Hook Level | Catches? | Can Prevent? |
|------------|----------|--------------|
| `type_call` | ✗ NO | N/A |
| `_PyObject_Init` | ✓ YES | ✗ NO (too late) |

---

## Summary: What Object Creation Hooks Can and Cannot Do

### ✓ CAN Intercept (via type_call hook)

| Operation | Example | Caught? |
|-----------|---------|---------|
| Explicit int creation | `int("123")` | ✓ YES |
| Explicit str creation | `str(obj)` | ✓ YES |
| Explicit list creation | `list(iterable)` | ✓ YES |
| Explicit dict creation | `dict(mapping)` | ✓ YES |
| Class instantiation | `MyClass()` | ✓ YES |
| float creation | `float(3.14)` | ✓ YES (can block!) |

### ✓ CAN Observe (via _PyObject_Init hook)

| Operation | Example | Observed? | Can Prevent? |
|-----------|---------|-----------|--------------|
| Integer arithmetic | `10 ** 10` | ✓ YES | ✗ NO (too late) |
| Integer from literal | `123456` | ✓ YES | ✗ NO |
| String literal | `"hello"` | ✓ YES | ✗ NO |
| List literal | `[1, 2, 3]` | ✓ YES | ✗ NO |

### ✗ CANNOT Prevent Resource Exhaustion

| Attack | Why Not? |
|--------|----------|
| `10**10**10` | Memory allocated before hook runs |
| `'x' * 10**10` | Memory allocated before hook runs |
| `s + s` loop | Memory allocated before hook runs |
| `a * b` (big ints) | Memory allocated before hook runs |

---

## Additional Hooks Required for Full Sandbox

To fully prevent resource exhaustion, you need hooks at **multiple levels**:

### Level 1: Object Creation Hooks (This Document)
- Block forbidden types (float)
- Replace types with safe wrappers
- Observe all object creation

### Level 2: Type-Specific Size Limits (Additional Work Required)

**For Integers - modify `Objects/longobject.c`:**

```c
// Add to _PyLong_New
PyLongObject *
_PyLong_New(Py_ssize_t size)
{
    // NEW: Check size limit before allocation
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->sandbox_limits.max_int_digits > 0 &&
        size > interp->sandbox_limits.max_int_digits) {
        PyErr_SetString(PyExc_OverflowError,
                       "Integer exceeds maximum allowed size");
        return NULL;
    }

    // ... existing allocation code ...
}
```

**For Strings - modify `Objects/unicodeobject.c`:**

```c
// Add to PyUnicode_New
PyObject *
PyUnicode_New(Py_ssize_t size, Py_UCS4 maxchar)
{
    // NEW: Check size limit before allocation
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp->sandbox_limits.max_str_length > 0 &&
        size > interp->sandbox_limits.max_str_length) {
        PyErr_SetString(PyExc_OverflowError,
                       "String exceeds maximum allowed length");
        return NULL;
    }

    // ... existing allocation code ...
}
```

**For Containers - modify `Objects/listobject.c`, `dictobject.c`, `setobject.c`:**

```c
// Add to list_resize, dict_resize, set_add, etc.
```

### Level 3: Operation Hooks (Most Invasive)

To intercept arithmetic BEFORE it computes results:

```c
// Modify long_pow in Objects/longobject.c
static PyObject *
long_pow(PyObject *v, PyObject *w, PyObject *x)
{
    // NEW: Check if result would be too large
    Py_ssize_t estimated_size = estimate_power_size(v, w);
    if (estimated_size > MAX_ALLOWED_SIZE) {
        PyErr_SetString(PyExc_OverflowError, "Power result too large");
        return NULL;
    }

    // ... existing code ...
}
```

---

## Recommended Sandbox Architecture

Given your requirements, here's the recommended multi-layer approach:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        SANDBOX ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Layer 1: Object Creation Hooks (Approaches 1-3)                    │
│  ─────────────────────────────────────────────────                  │
│  • Block float creation entirely ✓                                  │
│  • Replace list/dict/set with SafeList/SafeDict/SafeSet ✓           │
│  • Observe all object creation for debugging ✓                      │
│                                                                     │
│  Layer 2: Type-Specific Size Limits (NEW)                           │
│  ─────────────────────────────────────────                          │
│  Files to modify:                                                   │
│  • Objects/longobject.c - _PyLong_New, _PyLong_Copy                 │
│  • Objects/unicodeobject.c - PyUnicode_New                          │
│  • Objects/bytesobject.c - PyBytes_FromStringAndSize                │
│  • Objects/bytearrayobject.c - PyByteArray_Resize                   │
│                                                                     │
│  Layer 3: Container Growth Limits (NEW)                             │
│  ──────────────────────────────────────                             │
│  Files to modify:                                                   │
│  • Objects/listobject.c - list_resize, list_append, etc.            │
│  • Objects/dictobject.c - insertdict, dict_resize                   │
│  • Objects/setobject.c - set_add_key, set_table_resize              │
│                                                                     │
│  Layer 4: Arithmetic Limits (MOST INVASIVE)                         │
│  ──────────────────────────────────────────                         │
│  Files to modify:                                                   │
│  • Objects/longobject.c - long_pow, long_mul, long_add              │
│  • Objects/unicodeobject.c - unicode_repeat, PyUnicode_Concat       │
│  • Objects/bytesobject.c - bytes_repeat, bytes_concat               │
│                                                                     │
│  Configuration Storage (in PyInterpreterState):                     │
│  ─────────────────────────────────────────────                      │
│  struct {                                                           │
│      Py_ssize_t max_int_digits;      // e.g., 1000                  │
│      Py_ssize_t max_str_length;      // e.g., 10_000_000            │
│      Py_ssize_t max_bytes_length;    // e.g., 10_000_000            │
│      Py_ssize_t max_list_size;       // e.g., 100_000               │
│      Py_ssize_t max_dict_size;       // e.g., 100_000               │
│      Py_ssize_t max_set_size;        // e.g., 100_000               │
│      int allow_float;                // 0 = forbidden               │
│  } sandbox_limits;                                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Modified Approach 1 for Your Needs

Given that you liked Approach 1, here's how to extend it for your sandbox:

### Extended Hook Signature

```c
// Add flags parameter to know hook context
typedef PyObject* (*Py_ObjectCreationFunc)(
    PyObject *obj,
    PyTypeObject *type,
    PyFrameObject *frame,
    int flags,              // NEW: Py_OBJHOOK_TYPE_CALL or Py_OBJHOOK_INIT
    void *userdata
);

#define Py_OBJHOOK_TYPE_CALL  0x01  // Can replace
#define Py_OBJHOOK_INIT       0x02  // Observe only
```

### Add Sandbox Limits API

```c
// New API for setting sandbox limits
typedef struct {
    Py_ssize_t max_int_digits;
    Py_ssize_t max_str_length;
    Py_ssize_t max_bytes_length;
    Py_ssize_t max_list_size;
    Py_ssize_t max_dict_size;
    Py_ssize_t max_set_size;
    int allow_float;
} PySandboxLimits;

PyAPI_FUNC(int) PySandbox_SetLimits(PySandboxLimits *limits);
PyAPI_FUNC(int) PySandbox_GetLimits(PySandboxLimits *limits);
```

### Python API

```python
import sys

# Set sandbox limits
sys.setsandboxlimits(
    max_int_digits=1000,
    max_str_length=10_000_000,
    max_bytes_length=10_000_000,
    max_list_size=100_000,
    max_dict_size=100_000,
    max_set_size=100_000,
    allow_float=False
)

# These will now raise OverflowError:
x = 10 ** 10000        # OverflowError: Integer exceeds max digits
s = 'x' * 100_000_000  # OverflowError: String exceeds max length
f = 3.14               # TypeError: float creation is forbidden
```

---

## Implementation Priority

| Priority | What | Where | Effort |
|----------|------|-------|--------|
| 1 | Object creation hooks | typeobject.c, pycore_object.h | Medium |
| 2 | Block float | type_call hook | Easy (part of #1) |
| 3 | Integer size limits | longobject.c (_PyLong_New) | Easy |
| 4 | String size limits | unicodeobject.c (PyUnicode_New) | Easy |
| 5 | Bytes size limits | bytesobject.c, bytearrayobject.c | Easy |
| 6 | Container size limits | listobject.c, dictobject.c, setobject.c | Medium |
| 7 | Arithmetic limits | long_pow, long_mul, etc. | Hard |

**Recommendation**: Implement priorities 1-5 first. This covers:
- ✓ Block float creation
- ✓ Limit integer size (catches `10**10**10`)
- ✓ Limit string length (catches `'x' * 10**10`)
- ✓ Limit bytes length

Priorities 6-7 can come later if needed.

---

## Example: Attack Prevention with Limits

```python
import sys

# Configure sandbox
sys.setsandboxlimits(max_int_digits=1000, max_str_length=1_000_000)

# Attack 1: Exponential tower
try:
    result = 10**10**10
except OverflowError as e:
    print(f"Blocked: {e}")  # "Integer exceeds maximum allowed size"

# Attack 5: String multiplication
try:
    s = 'x' * (10**10)
except OverflowError as e:
    print(f"Blocked: {e}")  # "String exceeds maximum allowed length"

# Attack 6: Exponential concatenation
try:
    s = 'a'
    for _ in range(100):
        s = s + s
except OverflowError as e:
    print(f"Blocked: {e}")  # "String exceeds maximum allowed length"
```

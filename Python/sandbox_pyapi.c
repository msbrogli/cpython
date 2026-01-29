/* Sandbox Python API: sys.sandbox object, context managers, hooks
 *
 * This file contains the Python-facing API for the sandbox including:
 * - sys.sandbox namespace object (_PySandboxObject)
 * - Property getters and setters
 * - Methods
 * - Context managers (scope, suspended_limits)
 * - Object creation hooks
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"
#include "frameobject.h"

/* ============ Object Creation Hook ============ */

/* Get current frame for hook */
static PyFrameObject *
get_current_pyframe(void)
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

/* Pre-allocated context strings for creation hook (lazy-initialized) */
static PyObject *_hook_context_type_call = NULL;
static PyObject *_hook_context_init = NULL;

/* Python callback trampoline */
static PyObject *
creation_hook_trampoline(PyObject *obj, PyTypeObject *type,
                         struct _frame *frame, int flags, void *userdata)
{
    PyObject *callback = (PyObject *)userdata;

    /* Get pre-allocated context string (lazy init) */
    PyObject *context;
    if (flags & Py_OBJHOOK_TYPE_CALL) {
        if (_hook_context_type_call == NULL) {
            _hook_context_type_call = PyUnicode_InternFromString("type_call");
            if (_hook_context_type_call == NULL) {
                return NULL;
            }
        }
        context = _hook_context_type_call;
    } else {
        if (_hook_context_init == NULL) {
            _hook_context_init = PyUnicode_InternFromString("init");
            if (_hook_context_init == NULL) {
                return NULL;
            }
        }
        context = _hook_context_init;
    }

    /* Build arguments: (obj, type, frame, context) */
    PyObject *frame_arg = frame ? (PyObject *)frame : Py_None;
    PyObject *args = Py_BuildValue("(OOOO)", obj, (PyObject *)type, frame_arg, context);

    if (args == NULL) {
        return NULL;
    }

    PyObject *result = PyObject_CallObject(callback, args);
    Py_DECREF(args);

    return result;
}

PyObject *
_PySandbox_CallCreationHook(PyObject *obj, PyTypeObject *type, int flags)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return obj;  /* No interpreter, skip hook */
    }

    _PyObjectCreationHook *hook_state = &interp->sandbox.creation_hook;

    /* Fast path: no hook installed */
    if (hook_state->hook_func == NULL && hook_state->hook_callback == NULL) {
        return obj;
    }

    /* Prevent recursion */
    if (hook_state->in_hook) {
        return obj;
    }

    hook_state->in_hook = 1;

    PyObject *result = obj;
    PyFrameObject *frame = get_current_pyframe();

    /* Call C hook if set */
    if (hook_state->hook_func != NULL) {
        PyObject *hook_result = hook_state->hook_func(
            obj, type, (struct _frame *)frame, flags, hook_state->hook_userdata
        );

        if (hook_result == NULL) {
            /* Hook raised exception */
            if (flags & Py_OBJHOOK_TYPE_CALL) {
                Py_DECREF(obj);
            }
            hook_state->in_hook = 0;
            return NULL;
        }

        if (hook_result != Py_None && (flags & Py_OBJHOOK_TYPE_CALL)) {
            /* Replace object (but not if hook returned same object) */
            if (hook_result != obj) {
                Py_DECREF(obj);
            }
            result = hook_result;
        } else {
            Py_DECREF(hook_result);
        }
    }

    /* Call Python callback if set */
    if (hook_state->hook_callback != NULL && result != NULL) {
        PyObject *hook_result = creation_hook_trampoline(
            result, type, (struct _frame *)frame, flags, hook_state->hook_callback
        );

        if (hook_result == NULL) {
            /* Hook raised exception */
            if (flags & Py_OBJHOOK_TYPE_CALL) {
                Py_DECREF(result);
            }
            hook_state->in_hook = 0;
            return NULL;
        }

        if (hook_result != Py_None && (flags & Py_OBJHOOK_TYPE_CALL)) {
            /* Replace object (but not if hook returned same object) */
            if (hook_result != result) {
                Py_DECREF(result);
            }
            result = hook_result;
        } else {
            Py_DECREF(hook_result);
        }
    }

    /* Note: frame is a borrowed reference from _PyFrame_GetFrameObject,
       do not DECREF it */
    hook_state->in_hook = 0;
    return result;
}

int
PySandbox_SetCreationHook(Py_ObjectCreationHookFunc hook, void *userdata)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PyObjectCreationHook *hook_state = &interp->sandbox.creation_hook;
    hook_state->hook_func = hook;
    hook_state->hook_userdata = userdata;

    return 0;
}

Py_ObjectCreationHookFunc
PySandbox_GetCreationHook(void **userdata)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        if (userdata) *userdata = NULL;
        return NULL;
    }

    _PyObjectCreationHook *hook_state = &interp->sandbox.creation_hook;
    if (userdata) *userdata = hook_state->hook_userdata;
    return hook_state->hook_func;
}

/* ============ sys.sandbox namespace object ============ */

/*
 * _PySandboxObject: singleton namespace object exposed as sys.sandbox.
 * Provides properties, methods, and context managers for all sandbox
 * functionality, replacing the flat sys.setsandbox/getsandbox functions.
 */

typedef struct {
    PyObject_HEAD
} _PySandboxObject;

/* ---- Forward declarations for context manager types ---- */
static PyTypeObject _PySandboxScopeContext_Type;
static PyTypeObject _PySandboxSuspendContext_Type;

/* ---- Helper: get interpreter state or set error ---- */
static inline PyInterpreterState *
sandbox_get_interp(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
    }
    return interp;
}

/* ============ Read/Write Property Getters & Setters ============ */

/* Py_ssize_t property getter/setter helpers */
#define SANDBOX_SSIZE_GETSET(attr_name, field_path)                        \
static PyObject *                                                          \
sandbox_get_##attr_name(_PySandboxObject *self, void *closure)             \
{                                                                          \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return NULL;                                       \
    return PyLong_FromSsize_t(interp->sandbox.field_path);                 \
}                                                                          \
static int                                                                 \
sandbox_set_##attr_name(_PySandboxObject *self, PyObject *value, void *closure) \
{                                                                          \
    if (_PySandbox_CheckConfigModification() < 0) return -1;               \
    if (value == NULL) {                                                   \
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");  \
        return -1;                                                         \
    }                                                                      \
    Py_ssize_t v = PyLong_AsSsize_t(value);                                \
    if (v == -1 && PyErr_Occurred()) return -1;                            \
    if (v < 0) {                                                           \
        PyErr_SetString(PyExc_ValueError, "value must be non-negative");   \
        return -1;                                                         \
    }                                                                      \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return -1;                                         \
    interp->sandbox.field_path = v;                                        \
    return 0;                                                              \
}

/* uint64_t property getter/setter helpers
 * Note: Validates that values don't exceed SANDBOX_MAX_LIMIT to prevent
 * integer overflow when doing comparisons like `count == max + 1` or
 * `count > max + ALLOCATION_GRACE_HEADROOM`. */
#define SANDBOX_UINT64_GETSET_WITH_HOOK(attr_name, field_path, hook)       \
static PyObject *                                                          \
sandbox_get_##attr_name(_PySandboxObject *self, void *closure)             \
{                                                                          \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return NULL;                                       \
    return PyLong_FromUnsignedLongLong(                                    \
        (unsigned long long)interp->sandbox.field_path);                   \
}                                                                          \
static int                                                                 \
sandbox_set_##attr_name(_PySandboxObject *self, PyObject *value, void *closure) \
{                                                                          \
    if (_PySandbox_CheckConfigModification() < 0) return -1;               \
    if (value == NULL) {                                                   \
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");  \
        return -1;                                                         \
    }                                                                      \
    unsigned long long v = PyLong_AsUnsignedLongLong(value);               \
    if (v == (unsigned long long)-1 && PyErr_Occurred()) return -1;        \
    if (v > SANDBOX_MAX_LIMIT) {                                           \
        PyErr_SetString(PyExc_OverflowError,                               \
                        #attr_name " exceeds maximum allowed value");      \
        return -1;                                                         \
    }                                                                      \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return -1;                                         \
    interp->sandbox.field_path = (uint64_t)v;                              \
    hook                                                                   \
    return 0;                                                              \
}

#define SANDBOX_UINT64_GETSET(attr_name, field_path) \
    SANDBOX_UINT64_GETSET_WITH_HOOK(attr_name, field_path, /* no hook */)

/* int (bool) property getter/setter helpers */
#define SANDBOX_BOOL_GETSET(attr_name, field_path)                         \
static PyObject *                                                          \
sandbox_get_##attr_name(_PySandboxObject *self, void *closure)             \
{                                                                          \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return NULL;                                       \
    return PyBool_FromLong(interp->sandbox.field_path);                    \
}                                                                          \
static int                                                                 \
sandbox_set_##attr_name(_PySandboxObject *self, PyObject *value, void *closure) \
{                                                                          \
    if (_PySandbox_CheckConfigModification() < 0) return -1;               \
    if (value == NULL) {                                                   \
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");  \
        return -1;                                                         \
    }                                                                      \
    int v = PyObject_IsTrue(value);                                        \
    if (v < 0) return -1;                                                  \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return -1;                                         \
    interp->sandbox.field_path = v;                                        \
    return 0;                                                              \
}

/* uint64_t read-only property getter helper */
#define SANDBOX_UINT64_GETTER(attr_name, field_path)                       \
static PyObject *                                                          \
sandbox_get_##attr_name(_PySandboxObject *self, void *closure)             \
{                                                                          \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return NULL;                                       \
    return PyLong_FromUnsignedLongLong(                                    \
        (unsigned long long)interp->sandbox.field_path);                   \
}

/* ---- Py_ssize_t R/W properties (limits) ---- */
SANDBOX_SSIZE_GETSET(max_int_digits, limits.max_int_digits)
SANDBOX_SSIZE_GETSET(max_str_length, limits.max_str_length)
SANDBOX_SSIZE_GETSET(max_bytes_length, limits.max_bytes_length)
SANDBOX_SSIZE_GETSET(max_list_size, limits.max_list_size)
SANDBOX_SSIZE_GETSET(max_dict_size, limits.max_dict_size)
SANDBOX_SSIZE_GETSET(max_set_size, limits.max_set_size)
SANDBOX_SSIZE_GETSET(max_tuple_size, limits.max_tuple_size)

/* ---- uint64_t R/W properties ---- */
SANDBOX_UINT64_GETSET(max_allocations, limits.max_allocations)
SANDBOX_UINT64_GETSET(max_iterations, limits.max_iterations)
SANDBOX_UINT64_GETSET(max_operations, limits.max_operations)

/* max_statements needs to update tracing state when changed */
#define UPDATE_TRACING_STATE_HOOK \
    { PyThreadState *tstate = _PyThreadState_GET(); \
      if (tstate != NULL) _PyThreadState_UpdateTracingState(tstate); }

SANDBOX_UINT64_GETSET_WITH_HOOK(max_statements, limits.max_statements, UPDATE_TRACING_STATE_HOOK)

/* ---- bool R/W properties ---- */
SANDBOX_BOOL_GETSET(allow_float, limits.allow_float)
SANDBOX_BOOL_GETSET(allow_complex, limits.allow_complex)
SANDBOX_BOOL_GETSET(allow_dunder_access, limits.allow_dunder_access)
SANDBOX_BOOL_GETSET(count_iterations_as_operations, limits.count_iterations_as_operations)
SANDBOX_BOOL_GETSET(allow_unsafe, limits.allow_unsafe)
SANDBOX_BOOL_GETSET(frozen_mode, frozen_mode)
SANDBOX_BOOL_GETSET(auto_mutable, auto_mutable)

/* opcode_restrict_mode needs special setter to update tracing state */
static PyObject *
sandbox_get_opcode_restrict_mode(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    return PyBool_FromLong(interp->sandbox.opcode_restrict_mode);
}

static int
sandbox_set_opcode_restrict_mode(_PySandboxObject *self, PyObject *value, void *closure)
{
    if (_PySandbox_CheckConfigModification() < 0) return -1;
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }
    int v = PyObject_IsTrue(value);
    if (v < 0) return -1;
    PySandbox_SetOpcodeRestrictMode(v);
    return 0;
}

/* banned_opcodes: frozenset getter / set|frozenset|None setter */
static PyObject *
sandbox_get_banned_opcodes(_PySandboxObject *self, void *closure)
{
    return PySandbox_GetBannedOpcodes();
}

static int
sandbox_set_banned_opcodes(_PySandboxObject *self, PyObject *value, void *closure)
{
    if (_PySandbox_CheckConfigModification() < 0) return -1;
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }
    return PySandbox_SetBannedOpcodes(value);
}

/* creation_hook: callable|None getter/setter */
static PyObject *
sandbox_get_creation_hook(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    PyObject *hook = interp->sandbox.creation_hook.hook_callback;
    if (hook == NULL) {
        Py_RETURN_NONE;
    }
    Py_INCREF(hook);
    return hook;
}

static int
sandbox_set_creation_hook(_PySandboxObject *self, PyObject *value, void *closure)
{
    if (_PySandbox_CheckConfigModification() < 0) return -1;
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return -1;
    _PyObjectCreationHook *hook_state = &interp->sandbox.creation_hook;
    if (value == Py_None) {
        Py_CLEAR(hook_state->hook_callback);
    } else {
        if (!PyCallable_Check(value)) {
            PyErr_SetString(PyExc_TypeError, "hook must be callable or None");
            return -1;
        }
        Py_INCREF(value);
        Py_XDECREF(hook_state->hook_callback);
        hook_state->hook_callback = value;
    }
    return 0;
}

/* ---- Read-only properties (counters) ---- */
SANDBOX_UINT64_GETTER(allocation_count, counters.allocation_count)
SANDBOX_UINT64_GETTER(statement_count, counters.statement_count)
SANDBOX_UINT64_GETTER(iteration_count, counters.iteration_count)
SANDBOX_UINT64_GETTER(operation_count, counters.operation_count)

/* suspended: read-only bool */
static PyObject *
sandbox_get_suspended(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    return PyBool_FromLong(interp->sandbox.suspended > 0);
}

/* ============ PyGetSetDef array ============ */

static PyGetSetDef sandbox_getsetters[] = {
    /* R/W Py_ssize_t */
    {"max_int_digits", (getter)sandbox_get_max_int_digits,
     (setter)sandbox_set_max_int_digits, "Max internal digit count for integers (0=no limit)", NULL},
    {"max_str_length", (getter)sandbox_get_max_str_length,
     (setter)sandbox_set_max_str_length, "Max string length (0=no limit)", NULL},
    {"max_bytes_length", (getter)sandbox_get_max_bytes_length,
     (setter)sandbox_set_max_bytes_length, "Max bytes length (0=no limit)", NULL},
    {"max_list_size", (getter)sandbox_get_max_list_size,
     (setter)sandbox_set_max_list_size, "Max list size (0=no limit)", NULL},
    {"max_dict_size", (getter)sandbox_get_max_dict_size,
     (setter)sandbox_set_max_dict_size, "Max dict size (0=no limit)", NULL},
    {"max_set_size", (getter)sandbox_get_max_set_size,
     (setter)sandbox_set_max_set_size, "Max set size (0=no limit)", NULL},
    {"max_tuple_size", (getter)sandbox_get_max_tuple_size,
     (setter)sandbox_set_max_tuple_size, "Max tuple size (0=no limit)", NULL},
    /* R/W uint64_t */
    {"max_allocations", (getter)sandbox_get_max_allocations,
     (setter)sandbox_set_max_allocations, "Max scoped allocations (0=no limit)", NULL},
    {"max_statements", (getter)sandbox_get_max_statements,
     (setter)sandbox_set_max_statements, "Max scoped statement executions (0=no limit)", NULL},
    {"max_iterations", (getter)sandbox_get_max_iterations,
     (setter)sandbox_set_max_iterations, "Max scoped iterator steps (0=no limit)", NULL},
    {"max_operations", (getter)sandbox_get_max_operations,
     (setter)sandbox_set_max_operations, "Max scoped SANDBOX_COUNT operations (0=no limit)", NULL},
    /* R/W bool */
    {"allow_float", (getter)sandbox_get_allow_float,
     (setter)sandbox_set_allow_float, "Allow float creation", NULL},
    {"allow_complex", (getter)sandbox_get_allow_complex,
     (setter)sandbox_set_allow_complex, "Allow complex creation", NULL},
    {"allow_dunder_access", (getter)sandbox_get_allow_dunder_access,
     (setter)sandbox_set_allow_dunder_access, "Allow dunder attribute access", NULL},
    {"count_iterations_as_operations", (getter)sandbox_get_count_iterations_as_operations,
     (setter)sandbox_set_count_iterations_as_operations, "Count iterator yields as operations", NULL},
    {"allow_unsafe", (getter)sandbox_get_allow_unsafe,
     (setter)sandbox_set_allow_unsafe, "Allow unsafe operations (compile, gc introspection, __iter__)", NULL},
    {"frozen_mode", (getter)sandbox_get_frozen_mode,
     (setter)sandbox_set_frozen_mode, "Global frozen mode", NULL},
    {"auto_mutable", (getter)sandbox_get_auto_mutable,
     (setter)sandbox_set_auto_mutable, "Auto-mutable mode for new objects in scope", NULL},
    {"opcode_restrict_mode", (getter)sandbox_get_opcode_restrict_mode,
     (setter)sandbox_set_opcode_restrict_mode, "Opcode restriction mode", NULL},
    /* R/W special */
    {"banned_opcodes", (getter)sandbox_get_banned_opcodes,
     (setter)sandbox_set_banned_opcodes, "Banned opcodes (frozenset of ints)", NULL},
    {"creation_hook", (getter)sandbox_get_creation_hook,
     (setter)sandbox_set_creation_hook, "Object creation hook (callable or None)", NULL},
    /* R/O counters */
    {"allocation_count", (getter)sandbox_get_allocation_count,
     NULL, "Current scoped allocation count", NULL},
    {"statement_count", (getter)sandbox_get_statement_count,
     NULL, "Current scoped statement count", NULL},
    {"iteration_count", (getter)sandbox_get_iteration_count,
     NULL, "Current scoped iteration count", NULL},
    {"operation_count", (getter)sandbox_get_operation_count,
     NULL, "Current scoped operation count", NULL},
    {"suspended", (getter)sandbox_get_suspended,
     NULL, "True if sandbox is currently suspended", NULL},
    {NULL}  /* Sentinel */
};

/* ============ Methods ============ */

static PyObject *
sandbox_set_limits(_PySandboxObject *self, PyObject *args, PyObject *kwargs)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;

    static char *kwlist[] = {
        "max_int_digits", "max_str_length", "max_bytes_length",
        "max_list_size", "max_dict_size", "max_set_size", "max_tuple_size",
        "max_statements", "max_allocations",
        "max_iterations", "max_operations",
        "allow_float", "allow_complex", "allow_dunder_access",
        "count_iterations_as_operations", NULL
    };

    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;

    /* Use sentinel values to detect which kwargs were passed */
    Py_ssize_t max_int_digits = limits->max_int_digits;
    Py_ssize_t max_str_length = limits->max_str_length;
    Py_ssize_t max_bytes_length = limits->max_bytes_length;
    Py_ssize_t max_list_size = limits->max_list_size;
    Py_ssize_t max_dict_size = limits->max_dict_size;
    Py_ssize_t max_set_size = limits->max_set_size;
    Py_ssize_t max_tuple_size = limits->max_tuple_size;
    unsigned long long max_statements = (unsigned long long)limits->max_statements;
    unsigned long long max_allocations = (unsigned long long)limits->max_allocations;
    unsigned long long max_iterations = (unsigned long long)limits->max_iterations;
    unsigned long long max_operations = (unsigned long long)limits->max_operations;
    int allow_float = limits->allow_float;
    int allow_complex = limits->allow_complex;
    int allow_dunder_access = limits->allow_dunder_access;
    int count_iterations_as_operations = limits->count_iterations_as_operations;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|nnnnnnnKKKKpppp", kwlist,
                                     &max_int_digits, &max_str_length,
                                     &max_bytes_length, &max_list_size,
                                     &max_dict_size, &max_set_size,
                                     &max_tuple_size,
                                     &max_statements, &max_allocations,
                                     &max_iterations, &max_operations,
                                     &allow_float, &allow_complex,
                                     &allow_dunder_access,
                                     &count_iterations_as_operations)) {
        return NULL;
    }

    /* Validate that uint64_t limits don't exceed SANDBOX_MAX_LIMIT to prevent overflow */
    if (max_statements > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_statements exceeds maximum allowed value");
        return NULL;
    }
    if (max_allocations > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_allocations exceeds maximum allowed value");
        return NULL;
    }
    if (max_iterations > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_iterations exceeds maximum allowed value");
        return NULL;
    }
    if (max_operations > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_operations exceeds maximum allowed value");
        return NULL;
    }

    limits->max_int_digits = max_int_digits;
    limits->max_str_length = max_str_length;
    limits->max_bytes_length = max_bytes_length;
    limits->max_list_size = max_list_size;
    limits->max_dict_size = max_dict_size;
    limits->max_set_size = max_set_size;
    limits->max_tuple_size = max_tuple_size;
    limits->max_statements = (uint64_t)max_statements;
    limits->max_allocations = (uint64_t)max_allocations;
    limits->max_iterations = (uint64_t)max_iterations;
    limits->max_operations = (uint64_t)max_operations;
    limits->allow_float = allow_float;
    limits->allow_complex = allow_complex;
    limits->allow_dunder_access = allow_dunder_access;
    limits->count_iterations_as_operations = count_iterations_as_operations;

    /* Update tracing state */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate != NULL) {
        _PyThreadState_UpdateTracingState(tstate);
    }

    Py_RETURN_NONE;
}

static PyObject *
sandbox_get_limits(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;

    return Py_BuildValue(
        "{s:n, s:n, s:n, s:n, s:n, s:n, s:n, s:K, s:K, s:K, s:K, s:O, s:O, s:O, s:O}",
        "max_int_digits", limits->max_int_digits,
        "max_str_length", limits->max_str_length,
        "max_bytes_length", limits->max_bytes_length,
        "max_list_size", limits->max_list_size,
        "max_dict_size", limits->max_dict_size,
        "max_set_size", limits->max_set_size,
        "max_tuple_size", limits->max_tuple_size,
        "max_statements", (unsigned long long)limits->max_statements,
        "max_allocations", (unsigned long long)limits->max_allocations,
        "max_iterations", (unsigned long long)limits->max_iterations,
        "max_operations", (unsigned long long)limits->max_operations,
        "allow_float", limits->allow_float ? Py_True : Py_False,
        "allow_complex", limits->allow_complex ? Py_True : Py_False,
        "allow_dunder_access", limits->allow_dunder_access ? Py_True : Py_False,
        "count_iterations_as_operations", limits->count_iterations_as_operations ? Py_True : Py_False);
}

static PyObject *
sandbox_get_counts(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;

    return Py_BuildValue(
        "{s:K, s:K, s:K, s:K}",
        "allocation_count", (unsigned long long)sandbox->counters.allocation_count,
        "statement_count", (unsigned long long)sandbox->counters.statement_count,
        "iteration_count", (unsigned long long)sandbox->counters.iteration_count,
        "operation_count", (unsigned long long)sandbox->counters.operation_count);
}

static PyObject *
sandbox_reset_counts(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    _PySandbox_ResetCounters();
    Py_RETURN_NONE;
}

static PyObject *
sandbox_reset(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandbox_Reset(interp);
    Py_RETURN_NONE;
}

static PyObject *
sandbox_enter_scope(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    if (_PySandbox_EnterScope() < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_exit_scope(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    /* Idempotent: no error if not in scope */
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        clear_filenames(interp->sandbox.registered_filenames);
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_in_scope(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    return PyBool_FromLong(_PySandbox_IsInScope());
}

static PyObject *
sandbox_add_filename(_PySandboxObject *self, PyObject *arg)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    if (!PyUnicode_Check(arg)) {
        PyErr_SetString(PyExc_TypeError, "filename must be a string");
        return NULL;
    }
    if (_PySandbox_AddFilename(arg) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_remove_filename(_PySandboxObject *self, PyObject *arg)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    if (!PyUnicode_Check(arg)) {
        PyErr_SetString(PyExc_TypeError, "filename must be a string");
        return NULL;
    }
    if (_PySandbox_RemoveFilename(arg) < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_add_frame(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    if (_PySandbox_AddFrameToScope() < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_clear_filenames(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    _PySandbox_ClearFilenames();
    Py_RETURN_NONE;
}

static PyObject *
sandbox_suspend_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    int result = PySandbox_Suspend();
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromLong(result);
}

static PyObject *
sandbox_resume_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    int result = PySandbox_Resume();
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromLong(result);
}

static PyObject *
sandbox_freeze(_PySandboxObject *self, PyObject *obj)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PySandbox_FreezeObject(obj);
    Py_RETURN_NONE;
}

static PyObject *
sandbox_is_frozen(_PySandboxObject *self, PyObject *obj)
{
    return PyBool_FromLong(PySandbox_IsObjectFrozen(obj));
}

static PyObject *
sandbox_set_mutable(_PySandboxObject *self, PyObject *args)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PyObject *obj;
    int mutable = 1;
    if (!PyArg_ParseTuple(args, "O|p:set_mutable", &obj, &mutable)) {
        return NULL;
    }
    PySandbox_SetObjectMutable(obj, mutable);
    Py_RETURN_NONE;
}

/* Context manager factory methods */
static PyObject *
sandbox_scope_cm(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    /* Return a new _PySandboxScopeContext instance */
    return PyObject_CallNoArgs((PyObject *)&_PySandboxScopeContext_Type);
}

static PyObject *
sandbox_suspended_limits_cm(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    /* Return a new _PySandboxSuspendContext instance */
    return PyObject_CallNoArgs((PyObject *)&_PySandboxSuspendContext_Type);
}

static PyMethodDef sandbox_methods[] = {
    {"set_limits", _PyCFunction_CAST(sandbox_set_limits),
     METH_VARARGS | METH_KEYWORDS,
     "set_limits(**kwargs) -- Update sandbox limits (merge semantics)."},
    {"get_limits", (PyCFunction)sandbox_get_limits, METH_NOARGS,
     "get_limits() -> dict -- Return all limit values."},
    {"get_counts", (PyCFunction)sandbox_get_counts, METH_NOARGS,
     "get_counts() -> dict -- Return all counter values."},
    {"reset_counts", (PyCFunction)sandbox_reset_counts, METH_NOARGS,
     "reset_counts() -- Reset all counters to 0."},
    {"reset", (PyCFunction)sandbox_reset, METH_NOARGS,
     "reset() -- Reset all sandbox state to defaults."},
    {"enter_scope", (PyCFunction)sandbox_enter_scope, METH_NOARGS,
     "enter_scope() -- Enter sandbox scope (register current frame)."},
    {"exit_scope", (PyCFunction)sandbox_exit_scope, METH_NOARGS,
     "exit_scope() -- Exit sandbox scope (clear registered filenames)."},
    {"in_scope", (PyCFunction)sandbox_in_scope, METH_NOARGS,
     "in_scope() -> bool -- Check if currently in sandbox scope."},
    {"add_filename", (PyCFunction)sandbox_add_filename, METH_O,
     "add_filename(name) -- Register a filename for scope tracking."},
    {"remove_filename", (PyCFunction)sandbox_remove_filename, METH_O,
     "remove_filename(name) -- Unregister a filename from scope tracking."},
    {"add_frame", (PyCFunction)sandbox_add_frame, METH_NOARGS,
     "add_frame() -- Register current frame's filename for scope tracking."},
    {"clear_filenames", (PyCFunction)sandbox_clear_filenames, METH_NOARGS,
     "clear_filenames() -- Clear all registered filenames."},
    {"suspend", (PyCFunction)sandbox_suspend_method, METH_NOARGS,
     "suspend() -> int -- Suspend sandbox limits. Returns new suspend count."},
    {"resume", (PyCFunction)sandbox_resume_method, METH_NOARGS,
     "resume() -> int -- Resume sandbox limits. Returns new suspend count."},
    {"freeze", (PyCFunction)sandbox_freeze, METH_O,
     "freeze(obj) -- Freeze an object (prevent attribute modifications)."},
    {"is_frozen", (PyCFunction)sandbox_is_frozen, METH_O,
     "is_frozen(obj) -> bool -- Check if an object is frozen."},
    {"set_mutable", (PyCFunction)sandbox_set_mutable, METH_VARARGS,
     "set_mutable(obj, mutable=True) -- Mark an object as mutable."},
    {"scope", (PyCFunction)sandbox_scope_cm, METH_NOARGS,
     "scope() -- Return a context manager for sandbox scope."},
    {"suspended_limits", (PyCFunction)sandbox_suspended_limits_cm, METH_NOARGS,
     "suspended_limits() -- Return a context manager that suspends limits."},
    {NULL, NULL}  /* Sentinel */
};

/* ============ repr ============ */

static PyObject *
sandbox_repr(_PySandboxObject *self)
{
    return PyUnicode_FromString("<sys.sandbox>");
}

/* ============ Context Manager Types ============ */

/* _PySandboxScopeContext: __enter__ calls EnterScope, __exit__ calls ExitScope.
 * Stores the filename added on __enter__ so __exit__ only removes that one. */

typedef struct {
    PyObject_HEAD
    PyObject *filename;  /* The filename added by this context, or NULL */
} _PySandboxScopeContext;

static void
scope_ctx_dealloc(_PySandboxScopeContext *self)
{
    Py_XDECREF(self->filename);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
scope_ctx_enter(_PySandboxScopeContext *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;

    /* Get current frame's filename before entering scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL || frame->f_code == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return NULL;
    }
    PyObject *filename = frame->f_code->co_filename;

    if (_PySandbox_EnterScope() < 0) {
        return NULL;
    }

    /* Save the filename so __exit__ can remove just this one */
    Py_INCREF(filename);
    Py_XDECREF(self->filename);
    self->filename = filename;

    Py_INCREF(self);
    return (PyObject *)self;
}

static PyObject *
scope_ctx_exit(_PySandboxScopeContext *self, PyObject *args)
{
    /* Only remove the filename added by this context, not all filenames */
    if (self->filename != NULL) {
        _PySandbox_RemoveFilename(self->filename);
        Py_CLEAR(self->filename);
    }
    Py_RETURN_NONE;
}

static PyMethodDef scope_ctx_methods[] = {
    {"__enter__", (PyCFunction)scope_ctx_enter, METH_NOARGS, NULL},
    {"__exit__", (PyCFunction)scope_ctx_exit, METH_VARARGS, NULL},
    {NULL}
};

static PyTypeObject _PySandboxScopeContext_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sandbox_scope_context",
    .tp_basicsize = sizeof(_PySandboxScopeContext),
    .tp_dealloc = (destructor)scope_ctx_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_methods = scope_ctx_methods,
    .tp_new = PyType_GenericNew,
};

/* _PySandboxSuspendContext: __enter__ calls Suspend, __exit__ calls Resume */

typedef struct {
    PyObject_HEAD
} _PySandboxSuspendContext;

static PyObject *
suspend_ctx_enter(_PySandboxSuspendContext *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    int result = PySandbox_Suspend();
    if (result < 0) {
        return NULL;
    }
    Py_INCREF(self);
    return (PyObject *)self;
}

static PyObject *
suspend_ctx_exit(_PySandboxSuspendContext *self, PyObject *args)
{
    int result = PySandbox_Resume();
    if (result < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyMethodDef suspend_ctx_methods[] = {
    {"__enter__", (PyCFunction)suspend_ctx_enter, METH_NOARGS, NULL},
    {"__exit__", (PyCFunction)suspend_ctx_exit, METH_VARARGS, NULL},
    {NULL}
};

static PyTypeObject _PySandboxSuspendContext_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sandbox_suspend_context",
    .tp_basicsize = sizeof(_PySandboxSuspendContext),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_methods = suspend_ctx_methods,
    .tp_new = PyType_GenericNew,
};

/* ============ _PySandboxObject Type ============ */

static PyTypeObject _PySandboxObject_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "sys.sandbox",
    .tp_basicsize = sizeof(_PySandboxObject),
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_DISALLOW_INSTANTIATION,
    .tp_getset = sandbox_getsetters,
    .tp_methods = sandbox_methods,
    .tp_repr = (reprfunc)sandbox_repr,
};

/* ============ Factory ============ */

static int _sandbox_types_ready = 0;

PyObject *
_PySandbox_NewObject(void)
{
    /* Lazy type initialization */
    if (!_sandbox_types_ready) {
        if (PyType_Ready(&_PySandboxObject_Type) < 0) {
            return NULL;
        }
        if (PyType_Ready(&_PySandboxScopeContext_Type) < 0) {
            return NULL;
        }
        if (PyType_Ready(&_PySandboxSuspendContext_Type) < 0) {
            return NULL;
        }
        _sandbox_types_ready = 1;
    }

    /* Allocate singleton */
    _PySandboxObject *obj = PyObject_New(_PySandboxObject, &_PySandboxObject_Type);
    if (obj == NULL) {
        return NULL;
    }
    /* Mark as mutable so property setters work even in frozen mode.
     * Use PySandbox_SetObjectMutable to avoid tail-call optimization
     * from skipping the flag set. */
    PySandbox_SetObjectMutable((PyObject *)obj, 1);
    return (PyObject *)obj;
}

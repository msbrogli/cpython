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
    /* Block from within sandbox scope. */
    if (_PySandbox_CheckConfigModification() < 0) {
        return -1;
    }

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
SANDBOX_SSIZE_GETSET(max_int_digits, config.max_int_digits)
SANDBOX_SSIZE_GETSET(max_str_length, config.max_str_length)
SANDBOX_SSIZE_GETSET(max_bytes_length, config.max_bytes_length)
SANDBOX_SSIZE_GETSET(max_list_size, config.max_list_size)
SANDBOX_SSIZE_GETSET(max_dict_size, config.max_dict_size)
SANDBOX_SSIZE_GETSET(max_set_size, config.max_set_size)
SANDBOX_SSIZE_GETSET(max_tuple_size, config.max_tuple_size)

/* ---- uint64_t R/W properties ---- */
SANDBOX_UINT64_GETSET(max_iterations, config.max_iterations)
SANDBOX_UINT64_GETSET(max_operations, config.max_operations)
SANDBOX_UINT64_GETSET(max_recursion_depth, config.max_recursion_depth)

/* ---- bool R/W properties ---- */
SANDBOX_BOOL_GETSET(allow_float, config.allow_float)
SANDBOX_BOOL_GETSET(allow_complex, config.allow_complex)
SANDBOX_BOOL_GETSET(allow_dunder_access, config.allow_dunder_access)
SANDBOX_BOOL_GETSET(count_iterations_as_operations, config.count_iterations_as_operations)
SANDBOX_BOOL_GETSET(allow_unsafe, config.allow_unsafe)
SANDBOX_BOOL_GETSET(allow_io, config.allow_io)
SANDBOX_BOOL_GETSET(frozen_mode, frozen_mode)
SANDBOX_BOOL_GETSET(auto_mutable, auto_mutable)
SANDBOX_BOOL_GETSET(import_restrict_mode, config.import_restrict_mode)
SANDBOX_BOOL_GETSET(import_allow_submodules, config.import_allow_submodules)
SANDBOX_BOOL_GETSET(module_access_restrict_mode, config.module_access_restrict_mode)
SANDBOX_BOOL_GETSET(allow_submodules, config.allow_submodules)

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

/* allowed_imports: frozenset getter / set|frozenset|iterable setter */
static PyObject *
sandbox_get_allowed_imports(_PySandboxObject *self, void *closure)
{
    return PySandbox_GetAllowedImports();
}

static int
sandbox_set_allowed_imports(_PySandboxObject *self, PyObject *value, void *closure)
{
    if (_PySandbox_CheckConfigModification() < 0) return -1;
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }
    return PySandbox_SetAllowedImports(value);
}

/* allowed_modules: frozenset getter / set|frozenset|iterable setter
 * Stored internally as frozenset for O(1) getter.
 * When module_access_restrict_mode=True, only these modules can be accessed. */
static PyObject *
sandbox_get_allowed_modules(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;

    PyObject *allowed = interp->sandbox.allowed_modules;
    if (allowed == NULL) {
        Py_RETURN_NONE;  /* NULL means no restriction (when mode is off) */
    }
    return Py_NewRef(allowed);
}

static int
sandbox_set_allowed_modules(_PySandboxObject *self, PyObject *value, void *closure)
{
    if (_PySandbox_CheckConfigModification() < 0) return -1;
    if (value == NULL) {
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");
        return -1;
    }

    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return -1;

    if (value == Py_None) {
        Py_CLEAR(interp->sandbox.allowed_modules);
        return 0;
    }

    /* Convert to frozenset for immutability and O(1) getter */
    PyObject *new_frozenset = PyFrozenSet_New(value);
    if (new_frozenset == NULL) {
        return -1;
    }

    Py_XSETREF(interp->sandbox.allowed_modules, new_frozenset);
    return 0;
}

/* ---- Read-only properties (counters) ---- */
SANDBOX_UINT64_GETTER(iteration_count, counters.iteration_count)
SANDBOX_UINT64_GETTER(operation_count, counters.operation_count)

/* recursion_depth: read-only, from thread state */
static PyObject *
sandbox_get_recursion_depth(_PySandboxObject *self, void *closure)
{
    PyThreadState *tstate = PyThreadState_Get();
    if (tstate == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current thread state");
        return NULL;
    }
    return PyLong_FromUnsignedLongLong(
        (unsigned long long)tstate->sandbox_recursion_depth);
}

/* suspended: read-only bool */
static PyObject *
sandbox_get_suspended(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    return PyBool_FromLong(interp->sandbox.suspend_depth > 0);
}

/* enabled: read-only bool (use enable()/disable() methods to modify) */
static PyObject *
sandbox_get_enabled(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    return PyBool_FromLong(interp->sandbox.enabled);
}

/* ============ PyGetSetDef array ============ */

static PyGetSetDef sandbox_getsetters[] = {
    /* Master enable flag (read-only, use enable()/disable() methods) */
    {"enabled", (getter)sandbox_get_enabled,
     NULL, "Master enable flag (read-only). Use enable()/disable() methods.", NULL},
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
    {"max_iterations", (getter)sandbox_get_max_iterations,
     (setter)sandbox_set_max_iterations, "Max scoped iterator steps (0=no limit)", NULL},
    {"max_operations", (getter)sandbox_get_max_operations,
     (setter)sandbox_set_max_operations, "Max scoped SANDBOX_COUNT operations (0=no limit)", NULL},
    {"max_recursion_depth", (getter)sandbox_get_max_recursion_depth,
     (setter)sandbox_set_max_recursion_depth, "Max sandbox recursion depth (0=no limit)", NULL},
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
    {"allow_io", (getter)sandbox_get_allow_io,
     (setter)sandbox_set_allow_io, "Allow I/O operations (file, socket, raw fd)", NULL},
    {"frozen_mode", (getter)sandbox_get_frozen_mode,
     (setter)sandbox_set_frozen_mode, "Global frozen mode", NULL},
    {"auto_mutable", (getter)sandbox_get_auto_mutable,
     (setter)sandbox_set_auto_mutable, "Auto-mutable mode for new objects in scope", NULL},
    {"opcode_restrict_mode", (getter)sandbox_get_opcode_restrict_mode,
     (setter)sandbox_set_opcode_restrict_mode, "Opcode restriction mode", NULL},
    {"import_restrict_mode", (getter)sandbox_get_import_restrict_mode,
     (setter)sandbox_set_import_restrict_mode, "Import restriction mode (True by default)", NULL},
    {"import_allow_submodules", (getter)sandbox_get_import_allow_submodules,
     (setter)sandbox_set_import_allow_submodules, "Allow submodules of allowed modules", NULL},
    {"module_access_restrict_mode", (getter)sandbox_get_module_access_restrict_mode,
     (setter)sandbox_set_module_access_restrict_mode, "Module access restriction mode (default False)", NULL},
    {"allow_submodules", (getter)sandbox_get_allow_submodules,
     (setter)sandbox_set_allow_submodules, "Allow submodules when parent module is allowed (default True)", NULL},
    /* R/W special */
    {"banned_opcodes", (getter)sandbox_get_banned_opcodes,
     (setter)sandbox_set_banned_opcodes, "Banned opcodes (frozenset of ints)", NULL},
    {"creation_hook", (getter)sandbox_get_creation_hook,
     (setter)sandbox_set_creation_hook, "Object creation hook (callable or None)", NULL},
    {"allowed_imports", (getter)sandbox_get_allowed_imports,
     (setter)sandbox_set_allowed_imports, "Allowed imports (set of (module, name) tuples)", NULL},
    {"allowed_modules", (getter)sandbox_get_allowed_modules,
     (setter)sandbox_set_allowed_modules, "Allowed modules for access (set of module names, None=no restriction)", NULL},
    /* R/O counters */
    {"iteration_count", (getter)sandbox_get_iteration_count,
     NULL, "Current scoped iteration count", NULL},
    {"operation_count", (getter)sandbox_get_operation_count,
     NULL, "Current scoped operation count", NULL},
    {"recursion_depth", (getter)sandbox_get_recursion_depth,
     NULL, "Current sandbox recursion depth (per-thread)", NULL},
    {"suspended", (getter)sandbox_get_suspended,
     NULL, "True if sandbox is currently suspended", NULL},
    {NULL}  /* Sentinel */
};

/* ============ Methods ============ */

static PyObject *
sandbox_set_config(_PySandboxObject *self, PyObject *args, PyObject *kwargs)
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;

    static char *kwlist[] = {
        "max_int_digits", "max_str_length", "max_bytes_length",
        "max_list_size", "max_dict_size", "max_set_size", "max_tuple_size",
        "max_iterations", "max_operations", "max_recursion_depth",
        "allow_float", "allow_complex", "allow_dunder_access",
        "count_iterations_as_operations", "allow_unsafe", "allow_io",
        "import_restrict_mode", "import_allow_submodules",
        "module_access_restrict_mode", "allow_submodules", NULL
    };

    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxConfig *config = &sandbox->config;

    /* Use current values as defaults (merge semantics) */
    Py_ssize_t max_int_digits = config->max_int_digits;
    Py_ssize_t max_str_length = config->max_str_length;
    Py_ssize_t max_bytes_length = config->max_bytes_length;
    Py_ssize_t max_list_size = config->max_list_size;
    Py_ssize_t max_dict_size = config->max_dict_size;
    Py_ssize_t max_set_size = config->max_set_size;
    Py_ssize_t max_tuple_size = config->max_tuple_size;
    unsigned long long max_iterations = (unsigned long long)config->max_iterations;
    unsigned long long max_operations = (unsigned long long)config->max_operations;
    unsigned long long max_recursion_depth = (unsigned long long)config->max_recursion_depth;
    int allow_float = config->allow_float;
    int allow_complex = config->allow_complex;
    int allow_dunder_access = config->allow_dunder_access;
    int count_iterations_as_operations = config->count_iterations_as_operations;
    int allow_unsafe = config->allow_unsafe;
    int allow_io = config->allow_io;
    int import_restrict_mode = config->import_restrict_mode;
    int import_allow_submodules = config->import_allow_submodules;
    int module_access_restrict_mode = config->module_access_restrict_mode;
    int allow_submodules = config->allow_submodules;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|nnnnnnnKKKpppppppppp", kwlist,
                                     &max_int_digits, &max_str_length,
                                     &max_bytes_length, &max_list_size,
                                     &max_dict_size, &max_set_size,
                                     &max_tuple_size,
                                     &max_iterations, &max_operations,
                                     &max_recursion_depth,
                                     &allow_float, &allow_complex,
                                     &allow_dunder_access,
                                     &count_iterations_as_operations,
                                     &allow_unsafe, &allow_io,
                                     &import_restrict_mode, &import_allow_submodules,
                                     &module_access_restrict_mode, &allow_submodules)) {
        return NULL;
    }

    /* Validate that uint64_t limits don't exceed SANDBOX_MAX_LIMIT to prevent overflow */
    if (max_iterations > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_iterations exceeds maximum allowed value");
        return NULL;
    }
    if (max_operations > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_operations exceeds maximum allowed value");
        return NULL;
    }
    if (max_recursion_depth > SANDBOX_MAX_LIMIT) {
        PyErr_SetString(PyExc_OverflowError, "max_recursion_depth exceeds maximum allowed value");
        return NULL;
    }

    config->max_int_digits = max_int_digits;
    config->max_str_length = max_str_length;
    config->max_bytes_length = max_bytes_length;
    config->max_list_size = max_list_size;
    config->max_dict_size = max_dict_size;
    config->max_set_size = max_set_size;
    config->max_tuple_size = max_tuple_size;
    config->max_iterations = (uint64_t)max_iterations;
    config->max_operations = (uint64_t)max_operations;
    config->max_recursion_depth = (uint64_t)max_recursion_depth;
    config->allow_float = allow_float;
    config->allow_complex = allow_complex;
    config->allow_dunder_access = allow_dunder_access;
    config->count_iterations_as_operations = count_iterations_as_operations;
    config->allow_unsafe = allow_unsafe;
    config->allow_io = allow_io;
    config->import_restrict_mode = import_restrict_mode;
    config->import_allow_submodules = import_allow_submodules;
    config->module_access_restrict_mode = module_access_restrict_mode;
    config->allow_submodules = allow_submodules;

    Py_RETURN_NONE;
}

static PyObject *
sandbox_get_config(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxConfig *config = &sandbox->config;

    return Py_BuildValue(
        "{s:n, s:n, s:n, s:n, s:n, s:n, s:n, s:K, s:K, s:K, "
        "s:O, s:O, s:O, s:O, s:O, s:O, s:O, s:O, s:O, s:O}",
        "max_int_digits", config->max_int_digits,
        "max_str_length", config->max_str_length,
        "max_bytes_length", config->max_bytes_length,
        "max_list_size", config->max_list_size,
        "max_dict_size", config->max_dict_size,
        "max_set_size", config->max_set_size,
        "max_tuple_size", config->max_tuple_size,
        "max_iterations", (unsigned long long)config->max_iterations,
        "max_operations", (unsigned long long)config->max_operations,
        "max_recursion_depth", (unsigned long long)config->max_recursion_depth,
        "allow_float", config->allow_float ? Py_True : Py_False,
        "allow_complex", config->allow_complex ? Py_True : Py_False,
        "allow_dunder_access", config->allow_dunder_access ? Py_True : Py_False,
        "count_iterations_as_operations", config->count_iterations_as_operations ? Py_True : Py_False,
        "allow_unsafe", config->allow_unsafe ? Py_True : Py_False,
        "allow_io", config->allow_io ? Py_True : Py_False,
        "import_restrict_mode", config->import_restrict_mode ? Py_True : Py_False,
        "import_allow_submodules", config->import_allow_submodules ? Py_True : Py_False,
        "module_access_restrict_mode", config->module_access_restrict_mode ? Py_True : Py_False,
        "allow_submodules", config->allow_submodules ? Py_True : Py_False);
}

static PyObject *
sandbox_get_counts(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxState *sandbox = &interp->sandbox;

    return Py_BuildValue(
        "{s:K, s:K}",
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

/* Default allowed modules - generally safe modules from stdlib */
static const char *DEFAULT_ALLOWED_MODULES[] = {
    /* Data types and collections */
    "json", "collections", "enum", "dataclasses", "typing", "types",
    "copy", "pprint", "reprlib",

    /* Math and numbers */
    "math", "decimal", "fractions", "statistics",

    /* String processing */
    "string", "re", "textwrap", "unicodedata",

    /* Date/time */
    "datetime", "calendar", "zoneinfo",

    /* Binary data */
    "struct", "base64", "binascii", "quopri", "uu",

    /* Cryptographic hashing (not encryption) */
    "hashlib", "hmac",

    /* Functional programming */
    "functools", "itertools", "operator",

    /* Context managers */
    "contextlib",

    /* Abstract base classes */
    "abc",

    /* File formats (parsing only, no I/O) */
    "csv", "html", "html.parser", "html.entities",

    /* Misc utilities */
    "bisect", "heapq", "array",
    "weakref", "graphlib",

    /* Constants */
    "errno", "stat",

    /* Compression (in-memory only) */
    "zlib",

    NULL  /* Sentinel */
};

static PyObject *
sandbox_use_default_allowed_modules(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;

    /* Build the set of default allowed modules */
    PyObject *modules_set = PySet_New(NULL);
    if (modules_set == NULL) return NULL;

    for (const char **p = DEFAULT_ALLOWED_MODULES; *p != NULL; p++) {
        PyObject *name = PyUnicode_FromString(*p);
        if (name == NULL) {
            Py_DECREF(modules_set);
            return NULL;
        }
        int rc = PySet_Add(modules_set, name);
        Py_DECREF(name);
        if (rc < 0) {
            Py_DECREF(modules_set);
            return NULL;
        }
    }

    /* Convert to frozenset */
    PyObject *frozenset = PyFrozenSet_New(modules_set);
    Py_DECREF(modules_set);
    if (frozenset == NULL) return NULL;

    /* Set allowed_modules and enable restrict mode */
    Py_XSETREF(interp->sandbox.allowed_modules, frozenset);
    interp->sandbox.config.module_access_restrict_mode = 1;

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
sandbox_enable_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PySandbox_Enable();
    Py_RETURN_NONE;
}

static PyObject *
sandbox_disable_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_CheckConfigModification() < 0) return NULL;
    PySandbox_Disable();
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
    {"set_config", _PyCFunction_CAST(sandbox_set_config),
     METH_VARARGS | METH_KEYWORDS,
     "set_config(**kwargs) -- Update sandbox config (merge semantics)."},
    {"get_config", (PyCFunction)sandbox_get_config, METH_NOARGS,
     "get_config() -> dict -- Return all config values."},
    {"get_counts", (PyCFunction)sandbox_get_counts, METH_NOARGS,
     "get_counts() -> dict -- Return all counter values."},
    {"reset_counts", (PyCFunction)sandbox_reset_counts, METH_NOARGS,
     "reset_counts() -- Reset all counters to 0."},
    {"reset", (PyCFunction)sandbox_reset, METH_NOARGS,
     "reset() -- Reset all sandbox state to defaults."},
    {"use_default_allowed_modules", (PyCFunction)sandbox_use_default_allowed_modules, METH_NOARGS,
     "use_default_allowed_modules() -- Set allowed_modules to safe defaults and enable module_access_restrict_mode."},
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
    {"enable", (PyCFunction)sandbox_enable_method, METH_NOARGS,
     "enable() -- Enable sandbox enforcement."},
    {"disable", (PyCFunction)sandbox_disable_method, METH_NOARGS,
     "disable() -- Disable sandbox enforcement."},
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

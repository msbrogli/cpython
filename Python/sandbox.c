/* Sandbox implementation: resource limits and object creation hooks
 *
 * Thread Safety Note:
 * -------------------
 * Sandbox limits and counters are per-interpreter state. In CPython 3.11,
 * the GIL (Global Interpreter Lock) protects all access to interpreter state,
 * so the non-atomic counter increments (global_allocation_count, etc.) are
 * safe. If CPython moves to per-interpreter GILs or free-threading, these
 * counters would need atomic operations or other synchronization.
 *
 * The sandbox is designed for single-threaded sandboxed execution where
 * untrusted code runs in isolation. Multi-threaded sandboxed execution
 * within the same interpreter is not a supported use case.
 */

#include "Python.h"
#include "pycore_frame.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "frameobject.h"

/* Forward declarations */
static void free_filenames(_PySandboxFilenameSet *set);

/* ============ Initialization ============ */

/* Forward declaration of the wrapper type - defined at end of file */
extern PyTypeObject _PySandboxIteratorWrapper_Type;

/* Flag indicating whether the wrapper type has been initialized.
 * This is checked by _PySandbox_WrapIterator to avoid using the type
 * before it's ready. The type is initialized lazily on first use because
 * _PySandbox_Init is called too early in interpreter startup (before
 * thread state is available) for PyType_Ready to work. */
static int _sandbox_wrapper_type_ready = 0;

/* Initialize the sandbox iterator wrapper type.
 * This must be called lazily, not during _PySandbox_Init, because
 * PyType_Ready requires a valid thread state which isn't available
 * during early interpreter initialization.
 * Returns 0 on success, -1 on error (exception set). */
static int
_PySandbox_InitWrapperType(void)
{
    if (_sandbox_wrapper_type_ready) {
        return 0;
    }
    if (PyType_Ready(&_PySandboxIteratorWrapper_Type) < 0) {
        return -1;
    }
    _sandbox_wrapper_type_ready = 1;
    return 0;
}

void
_PySandbox_Init(PyInterpreterState *interp)
{
    /* Note: We don't initialize the iterator wrapper type here because
     * _PySandbox_Init is called during init_interpreter before thread
     * state is available. The type is initialized lazily in
     * _PySandbox_WrapIterator when first needed. */

    /* Initialize with defaults (no limits) */
    interp->sandbox.limits.max_int_digits = 0;
    interp->sandbox.limits.max_str_length = 0;
    interp->sandbox.limits.max_bytes_length = 0;
    interp->sandbox.limits.max_list_size = 0;
    interp->sandbox.limits.max_dict_size = 0;
    interp->sandbox.limits.max_set_size = 0;
    interp->sandbox.limits.max_tuple_size = 0;

    /* Global allocation limits */
    interp->sandbox.limits.global_max_allocations = 0;
    interp->sandbox.limits.global_allocation_count = 0;

    /* Scoped limits */
    interp->sandbox.limits.scope_max_statements = 0;
    interp->sandbox.limits.scope_statement_count = 0;
    interp->sandbox.limits.scope_max_allocations = 0;
    interp->sandbox.limits.scope_allocation_count = 0;
    interp->sandbox.limits.scope_max_iterations = 0;
    interp->sandbox.limits.scope_iteration_count = 0;

    /* Registered filenames set (lazy-initialized) */
    interp->sandbox.limits.registered_filenames.filenames = NULL;
    interp->sandbox.limits.registered_filenames.capacity = 0;
    interp->sandbox.limits.registered_filenames.count = 0;

    interp->sandbox.limits.allow_float = 1;
    interp->sandbox.limits.allow_complex = 1;
    interp->sandbox.limits.in_check = 0;
    interp->sandbox.limits.suspended = 0;
    interp->sandbox.limits.allow_dunder_access = 1;

    interp->sandbox.creation_hook.hook_func = NULL;
    interp->sandbox.creation_hook.hook_userdata = NULL;
    interp->sandbox.creation_hook.hook_callback = NULL;
    interp->sandbox.creation_hook.in_hook = 0;

    interp->sandbox.frozen_mode = 0;
    interp->sandbox.opcode_restrict_mode = 0;
    _PySandbox_OpcodeSet_ZERO(&interp->sandbox.banned_opcodes);
}

void
_PySandbox_Fini(PyInterpreterState *interp)
{
    /* Free registered filenames set */
    free_filenames(&interp->sandbox.limits.registered_filenames);

    Py_CLEAR(interp->sandbox.creation_hook.hook_callback);
    interp->sandbox.creation_hook.hook_func = NULL;
    interp->sandbox.creation_hook.hook_userdata = NULL;
}

/* ============ Limit Checking ============ */

/* Helper to get current interpreter's sandbox limits */
static inline _PySandboxLimits *
get_sandbox_limits(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return NULL;
    }
    return &interp->sandbox.limits;
}

/* Macro to reduce boilerplate in _PySandbox_Check* functions.
 * Returns 0 (allow) early if:
 * - No interpreter state available
 * - The specific limit is not set (0)
 * - Already in a recursive check
 * - Sandbox is suspended
 */
#define _PYSANDBOX_CHECK_PROLOGUE(limit_field) \
    _PySandboxLimits *limits = get_sandbox_limits(); \
    if (limits == NULL || limits->limit_field == 0 || \
        limits->in_check || limits->suspended) { \
        return 0; \
    }

int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_int_digits)

    if (ndigits > limits->max_int_digits) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, limits->max_int_digits);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckStrLength(Py_ssize_t length)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_str_length)

    if (length > limits->max_str_length) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "String length (%zd) exceeds sandbox limit (%zd)",
                     length, limits->max_str_length);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckBytesLength(Py_ssize_t length)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_bytes_length)

    if (length > limits->max_bytes_length) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Bytes length (%zd) exceeds sandbox limit (%zd)",
                     length, limits->max_bytes_length);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckListSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_list_size)

    if (size > limits->max_list_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "List size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_list_size);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckDictSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_dict_size)

    if (size > limits->max_dict_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Dict size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_dict_size);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckSetSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_set_size)

    if (size > limits->max_set_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Set size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_set_size);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTupleSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_tuple_size)

    if (size > limits->max_tuple_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Tuple size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_tuple_size);
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->suspended) {
        return 0;  /* No limits active or suspended */
    }

    /* Check float */
    if (!limits->allow_float && type == &PyFloat_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        return -1;
    }

    /* Check complex */
    if (!limits->allow_complex && type == &PyComplex_Type) {
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
        return -1;
    }

    return 0;
}

/* Grace allocation headroom to allow for error handling after limit is hit.
 * This allows Python to format and print MemoryError without cascading failures. */
#define ALLOCATION_GRACE_HEADROOM 1000

/* Initial capacity for registered filenames set */
#define FILENAMES_INITIAL_CAPACITY 8

/* ============ Registered Filenames Set ============ */

/* Check if a filename is in the registered set.
 *
 * Performance: O(n) linear search where n = number of registered filenames.
 * This is acceptable for typical use cases where n < 10. For sandboxing,
 * usually only 1-3 filenames are registered (the sandboxed code's filename
 * and perhaps a few helper modules). If larger sets become common,
 * consider hash-based lookup (PySet).
 */
static int
filename_is_registered(_PySandboxFilenameSet *set, PyObject *filename)
{
    if (set->filenames == NULL || set->count == 0 || filename == NULL) {
        return 0;
    }

    for (size_t i = 0; i < set->count; i++) {
        PyObject *registered = set->filenames[i];
        if (registered == filename) {
            return 1;  /* Same object - quick match */
        }
        /* String comparison for interned strings with different addresses */
        int cmp = PyUnicode_Compare(filename, registered);
        if (cmp == 0 && !PyErr_Occurred()) {
            return 1;
        }
        PyErr_Clear();  /* Clear any comparison error */
    }
    return 0;
}

/* Check if current frame is in sandbox scope.
 * A frame is in scope if its co_filename is in the registered set. */
static int
frame_in_sandbox_scope(_PySandboxFilenameSet *set, _PyInterpreterFrame *frame)
{
    if (set->filenames == NULL || set->count == 0 || frame == NULL) {
        return 0;
    }

    /* Skip incomplete frames to get the actual executing frame */
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    if (frame == NULL) {
        return 0;
    }

    /* Check if current frame's filename is registered */
    return filename_is_registered(set, frame->f_code->co_filename);
}

/* Initialize the filenames set */
static int
init_filenames(_PySandboxFilenameSet *set)
{
    if (set->filenames == NULL) {
        set->filenames = PyMem_RawCalloc(FILENAMES_INITIAL_CAPACITY,
                                         sizeof(PyObject *));
        if (set->filenames == NULL) {
            PyErr_NoMemory();
            return -1;
        }
        set->capacity = FILENAMES_INITIAL_CAPACITY;
        set->count = 0;
    }
    return 0;
}

/* Add a filename to the registered set */
static int
add_filename_to_set(_PySandboxFilenameSet *set, PyObject *filename)
{
    if (!PyUnicode_Check(filename)) {
        PyErr_SetString(PyExc_TypeError, "filename must be a string");
        return -1;
    }

    if (init_filenames(set) < 0) {
        return -1;
    }

    /* Check if already registered (idempotent) */
    if (filename_is_registered(set, filename)) {
        return 0;
    }

    /* Grow if needed.
     * Note: On realloc failure, set->filenames remains valid (not freed),
     * so we can safely return -1 without memory corruption. */
    if (set->count >= set->capacity) {
        size_t new_capacity = set->capacity * 2;
        PyObject **new_filenames = PyMem_RawRealloc(set->filenames,
                                                     new_capacity * sizeof(PyObject *));
        if (new_filenames == NULL) {
            PyErr_NoMemory();
            return -1;
        }
        set->filenames = new_filenames;
        set->capacity = new_capacity;
    }

    /* Add with strong reference */
    Py_INCREF(filename);
    set->filenames[set->count++] = filename;
    return 0;
}

/* Remove a filename from the registered set */
static int
remove_filename_from_set(_PySandboxFilenameSet *set, PyObject *filename)
{
    if (set->filenames == NULL || set->count == 0) {
        return 0;  /* Nothing to remove */
    }

    for (size_t i = 0; i < set->count; i++) {
        PyObject *registered = set->filenames[i];
        int match = (registered == filename);
        if (!match) {
            int cmp = PyUnicode_Compare(filename, registered);
            match = (cmp == 0 && !PyErr_Occurred());
            PyErr_Clear();
        }
        if (match) {
            /* Found it - remove by swapping with last element */
            Py_DECREF(registered);
            set->count--;
            if (i < set->count) {
                set->filenames[i] = set->filenames[set->count];
            }
            set->filenames[set->count] = NULL;
            return 1;  /* Removed */
        }
    }
    return 0;  /* Not found */
}

/* Clear all registered filenames (for exit scope) */
static void
clear_filenames(_PySandboxFilenameSet *set)
{
    if (set->filenames != NULL) {
        for (size_t i = 0; i < set->count; i++) {
            Py_XDECREF(set->filenames[i]);
            set->filenames[i] = NULL;
        }
        set->count = 0;
    }
}

/* Free the filenames set (for finalization) */
static void
free_filenames(_PySandboxFilenameSet *set)
{
    if (set->filenames != NULL) {
        for (size_t i = 0; i < set->count; i++) {
            Py_XDECREF(set->filenames[i]);
        }
        PyMem_RawFree(set->filenames);
        set->filenames = NULL;
        set->capacity = 0;
        set->count = 0;
    }
}

/* Get the current interpreter frame */
static _PyInterpreterFrame *
get_current_interpreter_frame(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->cframe == NULL) {
        return NULL;
    }
    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    return frame;
}

/* _PySandbox_CheckAllocation - Check allocation against limits
 *
 * This function is called from gc.c when GC-tracked objects are created.
 * It handles both global and scoped allocation limits.
 *
 * Design decisions:
 * - Counters are always incremented (for monitoring), even if no limit is set
 * - Scoped counting only occurs when current frame's filename is registered
 * - Grace headroom (ALLOCATION_GRACE_HEADROOM) allows error handling to
 *   allocate objects for exception formatting after limit is hit
 * - Only raises error on the first allocation past the limit (count == max+1)
 *   to avoid cascading failures during error handling
 * - If an error is already set, skip raising another (prevents infinite loops)
 *
 * Returns: 0 if allocation OK, -1 if limit exceeded (exception set)
 */
int
_PySandbox_CheckAllocation(void)
{
    /* Get thread state first - if not available, skip check */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    /* Get interpreter state - if not available, skip check */
    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Skip counting during recursive checks or when suspended */
    if (limits->in_check || limits->suspended) {
        return 0;
    }

    /* Always increment global allocation count (for monitoring) */
    limits->global_allocation_count++;

    /* Check if in sandbox scope for scoped counting.
     * Frame is in scope if its co_filename is in the registered set. */
    int in_scope = 0;
    if (limits->registered_filenames.count > 0) {
        _PyInterpreterFrame *current = get_current_interpreter_frame();
        if (current != NULL) {
            in_scope = frame_in_sandbox_scope(&limits->registered_filenames, current);
        }
    }

    /* Increment scoped count if in scope */
    if (in_scope) {
        limits->scope_allocation_count++;
    }

    /* If there's already an error set, don't raise another one.
     * This prevents allocation failures during error handling. */
    if (PyErr_Occurred()) {
        return 0;
    }

    /* Check global limit (if set) */
    if (limits->global_max_allocations > 0) {
        /* Hard limit: grace allocations exhausted, fail unconditionally */
        if (limits->global_allocation_count > limits->global_max_allocations + ALLOCATION_GRACE_HEADROOM) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox global allocation limit exceeded");
            return -1;
        }
        /* Soft limit: raise MemoryError only on the first allocation past the limit */
        if (limits->global_allocation_count == limits->global_max_allocations + 1) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox global allocation limit exceeded");
            return -1;
        }
    }

    /* Check scoped limit (if in scope and limit set) */
    if (in_scope && limits->scope_max_allocations > 0) {
        /* Hard limit: grace allocations exhausted, fail unconditionally */
        if (limits->scope_allocation_count > limits->scope_max_allocations + ALLOCATION_GRACE_HEADROOM) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox scoped allocation limit exceeded");
            return -1;
        }
        /* Soft limit: raise MemoryError only on the first allocation past the limit */
        if (limits->scope_allocation_count == limits->scope_max_allocations + 1) {
            PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox scoped allocation limit exceeded");
            return -1;
        }
    }

    return 0;
}

/* ============ Scoped Statement Checking ============ */

/* _PySandbox_CheckScopeStatement - Check statement execution against limit
 *
 * This function is called from ceval.c for each statement executed.
 * It only counts statements when:
 * - A statement limit is configured (scope_max_statements > 0)
 * - Sandbox is not suspended and not in recursive check
 * - At least one filename is registered for scope tracking
 * - Current frame's co_filename matches a registered filename
 *
 * The error is raised exactly once (at count == max+1) to allow error
 * handling code to execute without triggering additional errors.
 *
 * Returns: 0 if OK, -1 if limit exceeded (RuntimeError set)
 */
int
_PySandbox_CheckScopeStatement(void)
{
    /* Get thread state first - if not available, skip check */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    /* Get interpreter state - if not available, skip check */
    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Skip if no statement limit set, or if suspended/in_check */
    if (limits->scope_max_statements == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    /* Skip if no registered filenames */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    /* Check if current frame's filename is in the registered set */
    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    /* Increment statement count */
    limits->scope_statement_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (limits->scope_statement_count == limits->scope_max_statements + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox statement limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}

/* ============ Scoped Iteration Checking ============ */

/* _PySandbox_CheckIteration - Check iteration against limit
 *
 * This function is called from PyIter_Next() for each iterator step.
 * It only counts iterations when:
 * - An iteration limit is configured (scope_max_iterations > 0)
 * - Sandbox is not suspended and not in recursive check
 * - At least one filename is registered for scope tracking
 * - Current frame's co_filename matches a registered filename
 *
 * The error is raised exactly once (at count == max+1) to allow error
 * handling code to execute without triggering additional errors.
 *
 * Returns: 0 if OK, -1 if limit exceeded (RuntimeError set)
 */
int
_PySandbox_CheckIteration(void)
{
    /* Get thread state first - if not available, skip check */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    /* Get interpreter state - if not available, skip check */
    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Skip if no iteration limit set, or if suspended/in_check */
    if (limits->scope_max_iterations == 0 ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    /* Skip if no registered filenames */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    /* Check if current frame's filename is in the registered set */
    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    /* Increment iteration count */
    limits->scope_iteration_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (limits->scope_iteration_count == limits->scope_max_iterations + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox iteration limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
}

/* ============ Dunder Access Checking ============ */

/* Check if a name contains "__" (dunder pattern) */
static int
is_dunder_name(PyObject *name)
{
    if (!PyUnicode_Check(name)) {
        return 0;
    }
    const char *str = PyUnicode_AsUTF8(name);
    if (str == NULL) {
        PyErr_Clear();
        return 0;
    }
    return strstr(str, "__") != NULL;
}

/* _PySandbox_CheckDunderAccess - Check if dunder attribute access is blocked
 *
 * This function is called from ceval.c for LOAD_ATTR, STORE_ATTR, DELETE_ATTR.
 * It blocks access to attributes containing "__" when:
 * - allow_dunder_access is disabled (0)
 * - Sandbox is not suspended and not in recursive check
 * - At least one filename is registered for scope tracking
 * - Current frame's co_filename matches a registered filename
 *
 * Returns: 0 if access allowed, -1 if blocked (AttributeError set)
 */
int
_PySandbox_CheckDunderAccess(PyObject *name)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->allow_dunder_access ||
        limits->in_check || limits->suspended) {
        return 0;
    }

    if (!is_dunder_name(name)) {
        return 0;
    }

    /* Check if in sandbox scope */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL || !frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;
    }

    /* Block dunder access */
    limits->in_check = 1;
    PyErr_Format(PyExc_SandboxAttributeError,
                 "dunder attribute access blocked in sandbox: '%U'", name);
    limits->in_check = 0;
    return -1;
}

/* ============ Sandbox Scope Management ============ */

int
_PySandbox_EnterScope(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No thread state");
        return -1;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Get current frame and add its filename to registered set */
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return -1;
    }

    if (add_filename_to_set(&limits->registered_filenames,
                            frame->f_code->co_filename) < 0) {
        return -1;
    }

    /* Reset scope counters */
    limits->scope_statement_count = 0;
    limits->scope_allocation_count = 0;
    limits->scope_iteration_count = 0;

    return 0;
}

int
_PySandbox_ExitScope(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Clear all registered filenames */
    clear_filenames(&limits->registered_filenames);

    return 0;
}

int
_PySandbox_IsInScope(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Check if any filenames are registered */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (current == NULL) {
        return 0;
    }

    /* Current frame is in scope if its filename is registered */
    return frame_in_sandbox_scope(&limits->registered_filenames, current);
}

int
_PySandbox_AddFrameToScope(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No thread state");
        return -1;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Get current frame */
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return -1;
    }

    /* Add current frame's filename to the registered set */
    return add_filename_to_set(&limits->registered_filenames,
                               frame->f_code->co_filename);
}

/* ============ Counter Resetters ============ */

void
_PySandbox_ResetCounters(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.limits.global_allocation_count = 0;
        interp->sandbox.limits.scope_statement_count = 0;
        interp->sandbox.limits.scope_allocation_count = 0;
        interp->sandbox.limits.scope_iteration_count = 0;
    }
}

/* ============ Filename-Based Scope Management ============ */

int
_PySandbox_AddFilename(PyObject *filename)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    return add_filename_to_set(&limits->registered_filenames, filename);
}

int
_PySandbox_RemoveFilename(PyObject *filename)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    return remove_filename_from_set(&limits->registered_filenames, filename);
}

void
_PySandbox_ClearFilenames(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        /* Silent return is appropriate here: if there's no interpreter,
         * there are no filenames to clear. This can happen during
         * interpreter finalization or in abnormal shutdown scenarios. */
        return;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    clear_filenames(&limits->registered_filenames);
}

/* ============ Object Creation Hook ============ */

/* Get current frame for hook */
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

/* Python callback trampoline */
static PyObject *
creation_hook_trampoline(PyObject *obj, PyTypeObject *type,
                         struct _frame *frame, int flags, void *userdata)
{
    PyObject *callback = (PyObject *)userdata;

    /* Build context string */
    const char *context_str = (flags & Py_OBJHOOK_TYPE_CALL) ? "type_call" : "init";
    PyObject *context = PyUnicode_FromString(context_str);
    if (context == NULL) {
        return NULL;
    }

    /* Build arguments: (obj, type, frame, context) */
    PyObject *frame_arg = frame ? (PyObject *)frame : Py_None;
    PyObject *args = Py_BuildValue("(OOOO)", obj, (PyObject *)type, frame_arg, context);
    Py_DECREF(context);

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
    PyFrameObject *frame = get_current_frame();

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
            /* Replace object */
            Py_DECREF(obj);
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
            /* Replace object */
            Py_DECREF(result);
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

/* ============ Public C API ============ */

int
PySandbox_SetLimits(
    Py_ssize_t max_int_digits,
    Py_ssize_t max_str_length,
    Py_ssize_t max_bytes_length,
    Py_ssize_t max_list_size,
    Py_ssize_t max_dict_size,
    Py_ssize_t max_set_size,
    int allow_float)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    limits->max_int_digits = max_int_digits;
    limits->max_str_length = max_str_length;
    limits->max_bytes_length = max_bytes_length;
    limits->max_list_size = max_list_size;
    limits->max_dict_size = max_dict_size;
    limits->max_set_size = max_set_size;
    limits->allow_float = allow_float;

    return 0;
}

void
PySandbox_GetLimits(
    Py_ssize_t *max_int_digits,
    Py_ssize_t *max_str_length,
    Py_ssize_t *max_bytes_length,
    Py_ssize_t *max_list_size,
    Py_ssize_t *max_dict_size,
    Py_ssize_t *max_set_size,
    int *allow_float)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PySandboxLimits *limits = (interp != NULL) ? &interp->sandbox.limits : NULL;

    if (max_int_digits) *max_int_digits = limits ? limits->max_int_digits : 0;
    if (max_str_length) *max_str_length = limits ? limits->max_str_length : 0;
    if (max_bytes_length) *max_bytes_length = limits ? limits->max_bytes_length : 0;
    if (max_list_size) *max_list_size = limits ? limits->max_list_size : 0;
    if (max_dict_size) *max_dict_size = limits ? limits->max_dict_size : 0;
    if (max_set_size) *max_set_size = limits ? limits->max_set_size : 0;
    if (allow_float) *allow_float = limits ? limits->allow_float : 1;
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

/* ============ Suspend/Resume ============ */

int
PySandbox_Suspend(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    limits->suspended++;
    return limits->suspended;
}

int
PySandbox_Resume(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxLimits *limits = &interp->sandbox.limits;
    if (limits->suspended > 0) {
        limits->suspended--;
    }
    return limits->suspended;
}

int
PySandbox_IsSuspended(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;  /* No interpreter means no limits anyway */
    }

    return interp->sandbox.limits.suspended > 0;
}

/* ============ Frozen Mode ============ */

/* Check if attribute mutation is blocked on an object.
 * Returns 0 if mutation is allowed, -1 if blocked (sets SandboxAttributeError).
 *
 * Check order:
 * 1. Per-instance mutable flag (fast exit — always allow)
 * 2. Suspend state (if suspended, allow all mutations)
 * 3. Fast path: no frozen restrictions exist
 * 4. Scope check: only enforce within sandbox scope
 * 5. Per-instance frozen flag
 * 6. Global frozen mode
 */
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* Fast path: mutable objects are always allowed */
    if (Py_IS_MUTABLE(obj)) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.limits.suspended) {
        return 0;
    }

    /* Fast path: no frozen restrictions exist */
    int obj_frozen = Py_IS_FROZEN(obj);
    if (!obj_frozen && !interp->sandbox.frozen_mode) {
        return 0;
    }

    /* Frozen restrictions exist — only enforce within sandbox scope */
    _PySandboxLimits *limits = &interp->sandbox.limits;
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;  /* Not in scope — allow */
    }

    if (obj_frozen) {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify frozen object '%.100s'",
                     Py_TYPE(obj)->tp_name);
        return -1;
    }

    /* Global frozen mode (already checked it's true above) */
    PyErr_Format(PyExc_SandboxAttributeError,
                 "cannot modify '%.100s' object: sandbox frozen mode is active",
                 Py_TYPE(obj)->tp_name);
    return -1;
}

void
PySandbox_SetFrozenMode(int mode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.frozen_mode = mode ? 1 : 0;
    }
}

int
PySandbox_GetFrozenMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.frozen_mode;
}

void
PySandbox_FreezeObject(PyObject *obj)
{
    obj->ob_flags |= Py_OBJFLAGS_FROZEN;
}

int
PySandbox_IsObjectFrozen(PyObject *obj)
{
    return (obj->ob_flags & Py_OBJFLAGS_FROZEN) != 0;
}

void
PySandbox_SetObjectMutable(PyObject *obj, int mutable)
{
    if (mutable) {
        obj->ob_flags |= Py_OBJFLAGS_MUTABLE;
    } else {
        obj->ob_flags &= ~Py_OBJFLAGS_MUTABLE;
    }
}

/* ============ Opcode Restriction ============ */

/* _PySandbox_CheckOpcode - Check if an opcode is banned in sandbox scope
 *
 * Called from the DO_TRACING handler in ceval.c for every opcode dispatch
 * when tracing is active (which includes sandbox mode).
 *
 * Fast exits:
 * - opcode_restrict_mode == 0 (not active)
 * - suspended or in_check (recursion/error handling)
 * - opcode not in banned_opcodes bitmap
 * - current frame not in sandbox scope
 *
 * Returns: 0 if opcode allowed, -1 if banned (SandboxRuntimeError set)
 */
int
_PySandbox_CheckOpcode(int opcode)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast exit: mode not active */
    if (!sandbox->opcode_restrict_mode) {
        return 0;
    }

    _PySandboxLimits *limits = &sandbox->limits;

    /* Fast exit: suspended or in recursive check */
    if (limits->suspended || limits->in_check) {
        return 0;
    }

    /* Fast exit: opcode not banned */
    if (!_PySandbox_OpcodeSet_HAS(&sandbox->banned_opcodes, opcode)) {
        return 0;
    }

    /* Opcode is banned — check if we're in sandbox scope */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    /* Skip incomplete frames */
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    if (!frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;
    }

    /* Banned opcode in sandbox scope — raise error */
    limits->in_check = 1;
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Opcode %d is not allowed in sandbox scope", opcode);
    limits->in_check = 0;
    return -1;
}

void
PySandbox_SetOpcodeRestrictMode(int mode)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return;
    }
    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return;
    }
    interp->sandbox.opcode_restrict_mode = mode ? 1 : 0;
    _PyThreadState_UpdateTracingState(tstate);
}

int
PySandbox_GetOpcodeRestrictMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.opcode_restrict_mode;
}

int
PySandbox_SetBannedOpcodes(PyObject *opcode_set)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxOpcodeSet *banned = &interp->sandbox.banned_opcodes;

    /* None or empty → clear all */
    if (opcode_set == Py_None) {
        _PySandbox_OpcodeSet_ZERO(banned);
        return 0;
    }

    /* Must be an iterable of ints */
    PyObject *iter = PyObject_GetIter(opcode_set);
    if (iter == NULL) {
        return -1;
    }

    _PySandbox_OpcodeSet_ZERO(banned);

    PyObject *item;
    while ((item = PyIter_Next(iter)) != NULL) {
        long op = PyLong_AsLong(item);
        Py_DECREF(item);
        if (op == -1 && PyErr_Occurred()) {
            Py_DECREF(iter);
            return -1;
        }
        if (op < 0 || op > 255) {
            PyErr_Format(PyExc_ValueError,
                         "opcode must be in range 0..255, got %ld", op);
            Py_DECREF(iter);
            return -1;
        }
        _PySandbox_OpcodeSet_SET(banned, (int)op);
    }
    Py_DECREF(iter);

    if (PyErr_Occurred()) {
        return -1;  /* Error during iteration */
    }
    return 0;
}

PyObject *
PySandbox_GetBannedOpcodes(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return NULL;
    }

    _PySandboxOpcodeSet *banned = &interp->sandbox.banned_opcodes;

    PyObject *result = PySet_New(NULL);
    if (result == NULL) {
        return NULL;
    }

    for (int op = 0; op < 256; op++) {
        if (_PySandbox_OpcodeSet_HAS(banned, op)) {
            PyObject *val = PyLong_FromLong(op);
            if (val == NULL) {
                Py_DECREF(result);
                return NULL;
            }
            if (PySet_Add(result, val) < 0) {
                Py_DECREF(val);
                Py_DECREF(result);
                return NULL;
            }
            Py_DECREF(val);
        }
    }

    PyObject *frozen = PyFrozenSet_New(result);
    Py_DECREF(result);
    return frozen;
}

/* ============ Sandbox Iterator Wrapper ============ */

/* Sandbox iterator wrapper - wraps any iterator to check limits on each step.
 *
 * This provides protection against infinite iteration attacks for ALL call
 * sites that use PyObject_GetIter(), including:
 * - list(), tuple(), set(), frozenset()
 * - all(), any(), zip(), map(), filter(), enumerate()
 * - for loops (via GET_ITER opcode)
 * - sum(), min(), max(), sorted()
 * - deque.extend(), etc.
 *
 * By wrapping at the single point where iterators are created (PyObject_GetIter),
 * we automatically protect all 26+ direct tp_iternext call sites.
 */
typedef struct {
    PyObject_HEAD
    PyObject *wrapped;  /* The wrapped iterator (strong ref) */
} _PySandboxIteratorWrapper;

static void
sandbox_iter_wrapper_dealloc(_PySandboxIteratorWrapper *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->wrapped);
    PyObject_GC_Del(self);
}

static int
sandbox_iter_wrapper_traverse(_PySandboxIteratorWrapper *self, visitproc visit, void *arg)
{
    Py_VISIT(self->wrapped);
    return 0;
}

static int
sandbox_iter_wrapper_clear(_PySandboxIteratorWrapper *self)
{
    Py_CLEAR(self->wrapped);
    return 0;
}

static PyObject *
sandbox_iter_wrapper_iter(PyObject *self)
{
    Py_INCREF(self);
    return self;
}

static PyObject *
sandbox_iter_wrapper_iternext(_PySandboxIteratorWrapper *self)
{
    /* Check iteration limits BEFORE delegating */
    if (_PySandbox_CheckIteration() < 0) {
        return NULL;  /* Exception already set */
    }

    /* Delegate to wrapped iterator's tp_iternext */
    if (self->wrapped == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "sandbox iterator wrapper has no wrapped iterator");
        return NULL;
    }

    PyTypeObject *type = Py_TYPE(self->wrapped);
    if (type->tp_iternext == NULL) {
        PyErr_SetString(PyExc_TypeError,
                        "wrapped object is not an iterator");
        return NULL;
    }

    return (*type->tp_iternext)(self->wrapped);
}

PyTypeObject _PySandboxIteratorWrapper_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sandbox_iterator_wrapper",
    .tp_basicsize = sizeof(_PySandboxIteratorWrapper),
    .tp_dealloc = (destructor)sandbox_iter_wrapper_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_traverse = (traverseproc)sandbox_iter_wrapper_traverse,
    .tp_clear = (inquiry)sandbox_iter_wrapper_clear,
    .tp_iter = sandbox_iter_wrapper_iter,
    .tp_iternext = (iternextfunc)sandbox_iter_wrapper_iternext,
};

/* _PySandbox_WrapIterator - Wrap an iterator if sandbox scope is active.
 *
 * This function should be called on every iterator returned by PyObject_GetIter().
 * If the current execution is within a sandbox scope (a registered filename),
 * the iterator is wrapped to check iteration limits on each step.
 *
 * Parameters:
 *   iter: The iterator to potentially wrap (borrowed reference)
 *
 * Returns:
 *   - New reference to a wrapper iterator (if in sandbox scope)
 *   - New reference to the original iterator (if not in scope)
 *   - NULL on error (exception set)
 *
 * Note: The caller is responsible for decref'ing the original iterator
 * AFTER calling this function if it was returned from tp_iter.
 */
PyObject *
_PySandbox_WrapIterator(PyObject *iter)
{
    if (iter == NULL) {
        return NULL;
    }

    /* Safety check for early interpreter initialization.
     * During interpreter bootstrapping (freeze phase, etc.), thread state
     * may not be available. In this case, don't wrap. */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        Py_INCREF(iter);
        return iter;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        Py_INCREF(iter);
        return iter;
    }

    /* Check if we should wrap: sandbox scope must be active */
    if (!_PySandbox_IsInScope()) {
        Py_INCREF(iter);
        return iter;  /* No wrapping needed */
    }

    /* Initialize wrapper type lazily on first use.
     * This is done here instead of in _PySandbox_Init because we now
     * have a valid thread state. */
    if (!_sandbox_wrapper_type_ready) {
        if (_PySandbox_InitWrapperType() < 0) {
            /* Type initialization failed - don't wrap, just return original */
            PyErr_Clear();
            Py_INCREF(iter);
            return iter;
        }
    }

    /* Avoid wrapping an already-wrapped iterator */
    if (Py_TYPE(iter) == &_PySandboxIteratorWrapper_Type) {
        Py_INCREF(iter);
        return iter;
    }

    /* Create wrapper */
    _PySandboxIteratorWrapper *wrapper = PyObject_GC_New(
        _PySandboxIteratorWrapper, &_PySandboxIteratorWrapper_Type);
    if (wrapper == NULL) {
        return NULL;
    }

    Py_INCREF(iter);
    wrapper->wrapped = iter;
    PyObject_GC_Track(wrapper);

    return (PyObject *)wrapper;
}

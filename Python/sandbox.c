/* Sandbox implementation: resource limits and object creation hooks
 *
 * Thread Safety Note:
 * -------------------
 * Sandbox limits and counters are per-interpreter state. In CPython 3.11,
 * the GIL (Global Interpreter Lock) protects all access to interpreter state,
 * so the non-atomic counter increments (scope_allocation_count, etc.) are
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

    /* Scoped limits */
    interp->sandbox.limits.scope_max_statements = 0;
    interp->sandbox.limits.scope_statement_count = 0;
    interp->sandbox.limits.scope_max_allocations = 0;
    interp->sandbox.limits.scope_allocation_count = 0;
    interp->sandbox.limits.scope_max_iterations = 0;
    interp->sandbox.limits.scope_iteration_count = 0;
    interp->sandbox.limits.scope_max_operations = 0;
    interp->sandbox.limits.scope_operation_count = 0;

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
    interp->sandbox.auto_mutable_mode = 0;
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

/* Forward declarations for scope-checking functions used by prologue macro */
static int frame_in_sandbox_scope(_PySandboxFilenameSet *set, _PyInterpreterFrame *frame);
static _PyInterpreterFrame *get_current_interpreter_frame(void);

/* Macro to reduce boilerplate in _PySandbox_Check* functions.
 * Returns 0 (allow) early if:
 * - No interpreter state available
 * - The specific limit is not set (0)
 * - Already in a recursive check
 * - Sandbox is suspended
 * - No filenames registered (not in any scope)
 * - Current frame is not in sandbox scope
 */
#define _PYSANDBOX_CHECK_PROLOGUE(limit_field) \
    _PySandboxLimits *limits = get_sandbox_limits(); \
    if (limits == NULL || limits->limit_field == 0 || \
        limits->in_check || limits->suspended) { \
        return 0; \
    } \
    if (limits->registered_filenames.count == 0) { \
        return 0; \
    } \
    { \
        _PyInterpreterFrame *_prologue_frame = get_current_interpreter_frame(); \
        if (!frame_in_sandbox_scope(&limits->registered_filenames, _prologue_frame)) { \
            return 0; \
        } \
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
    if (limits == NULL || limits->suspended || limits->in_check) {
        return 0;  /* No limits active, suspended, or recursive check */
    }

    /* Fast path: if both types are allowed, nothing to check */
    if (limits->allow_float && limits->allow_complex) {
        return 0;
    }

    /* Scope check */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (!frame_in_sandbox_scope(&limits->registered_filenames, frame)) {
        return 0;
    }

    /* Check float */
    if (!limits->allow_float && type == &PyFloat_Type) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        limits->in_check = 0;
        return -1;
    }

    /* Check complex */
    if (!limits->allow_complex && type == &PyComplex_Type) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
        limits->in_check = 0;
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

/* _PySandbox_CheckAllocation - Check allocation against scoped limits
 *
 * This function is called from gc.c when GC-tracked objects are created.
 * It handles scoped allocation limits only (within sandbox scope).
 *
 * Design decisions:
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

    /* Early exit if no scoped allocation limit is set */
    if (limits->scope_max_allocations == 0) {
        return 0;
    }

    /* Check if in sandbox scope for scoped counting.
     * Frame is in scope if its co_filename is in the registered set. */
    if (limits->registered_filenames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (current == NULL) {
        return 0;
    }

    if (!frame_in_sandbox_scope(&limits->registered_filenames, current)) {
        return 0;
    }

    /* Increment scoped count */
    limits->scope_allocation_count++;

    /* If there's already an error set, don't raise another one.
     * This prevents allocation failures during error handling. */
    if (PyErr_Occurred()) {
        return 0;
    }

    /* Check scoped limit */
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

/* ============ Scoped Operation Checking (SANDBOX_COUNT opcode) ============ */

/* _PySandbox_CheckScopeOperation - Check operation execution against limit
 *
 * This function is called from ceval.c for each SANDBOX_COUNT opcode.
 * It only counts operations when:
 * - An operation limit is configured (scope_max_operations > 0)
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
_PySandbox_CheckScopeOperation(void)
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

    /* Skip if no operation limit set, or if suspended/in_check */
    if (limits->scope_max_operations == 0 ||
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

    /* Increment operation count */
    limits->scope_operation_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (limits->scope_operation_count == limits->scope_max_operations + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
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
    limits->scope_operation_count = 0;

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
        interp->sandbox.limits.scope_statement_count = 0;
        interp->sandbox.limits.scope_allocation_count = 0;
        interp->sandbox.limits.scope_iteration_count = 0;
        interp->sandbox.limits.scope_operation_count = 0;
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

/* ============ Auto-Mutable Mode ============ */

/* _PySandbox_MaybeMarkMutable - conditionally mark a newly created object
 * as mutable (Py_OBJFLAGS_MUTABLE) when auto_mutable_mode and frozen_mode
 * are both active and the current frame is within sandbox scope.
 *
 * This is called from MAKE_FUNCTION (ceval.c) and type_call (typeobject.c)
 * to automatically allow freshly created functions, classes, and instances
 * to be mutated while keeping imported modules frozen.
 */
void
_PySandbox_MaybeMarkMutable(PyObject *obj)
{
    assert(obj != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }
    /* Fast path: both flags must be on */
    if (!interp->sandbox.auto_mutable_mode || !interp->sandbox.frozen_mode) {
        return;
    }
    if (interp->sandbox.limits.suspended) {
        return;
    }
    if (interp->sandbox.limits.registered_filenames.count == 0) {
        return;
    }
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL) {
        return;
    }
    if (!frame_in_sandbox_scope(&interp->sandbox.limits.registered_filenames, frame)) {
        return;
    }
    obj->ob_flags |= Py_OBJFLAGS_MUTABLE;
}

void
PySandbox_SetAutoMutableMode(int mode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.auto_mutable_mode = mode ? 1 : 0;
    }
}

int
PySandbox_GetAutoMutableMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.auto_mutable_mode;
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

/* uint64_t property getter/setter helpers */
#define SANDBOX_UINT64_GETSET(attr_name, field_path)                       \
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
    if (value == NULL) {                                                   \
        PyErr_SetString(PyExc_AttributeError, "cannot delete attribute");  \
        return -1;                                                         \
    }                                                                      \
    unsigned long long v = PyLong_AsUnsignedLongLong(value);               \
    if (v == (unsigned long long)-1 && PyErr_Occurred()) return -1;        \
    PyInterpreterState *interp = sandbox_get_interp();                     \
    if (interp == NULL) return -1;                                         \
    interp->sandbox.field_path = (uint64_t)v;                              \
    return 0;                                                              \
}

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
SANDBOX_UINT64_GETSET(max_scope_allocations, limits.scope_max_allocations)
SANDBOX_UINT64_GETSET(max_scope_statements, limits.scope_max_statements)
SANDBOX_UINT64_GETSET(max_scope_iterations, limits.scope_max_iterations)
SANDBOX_UINT64_GETSET(max_scope_operations, limits.scope_max_operations)

/* ---- bool R/W properties ---- */
SANDBOX_BOOL_GETSET(allow_float, limits.allow_float)
SANDBOX_BOOL_GETSET(allow_complex, limits.allow_complex)
SANDBOX_BOOL_GETSET(allow_dunder_access, limits.allow_dunder_access)
SANDBOX_BOOL_GETSET(frozen_mode, frozen_mode)
SANDBOX_BOOL_GETSET(auto_mutable, auto_mutable_mode)

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
SANDBOX_UINT64_GETTER(scope_allocation_count, limits.scope_allocation_count)
SANDBOX_UINT64_GETTER(scope_statement_count, limits.scope_statement_count)
SANDBOX_UINT64_GETTER(scope_iteration_count, limits.scope_iteration_count)
SANDBOX_UINT64_GETTER(scope_operation_count, limits.scope_operation_count)

/* suspended: read-only bool */
static PyObject *
sandbox_get_suspended(_PySandboxObject *self, void *closure)
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    return PyBool_FromLong(interp->sandbox.limits.suspended > 0);
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
    {"max_scope_allocations", (getter)sandbox_get_max_scope_allocations,
     (setter)sandbox_set_max_scope_allocations, "Max scoped allocations (0=no limit)", NULL},
    {"max_scope_statements", (getter)sandbox_get_max_scope_statements,
     (setter)sandbox_set_max_scope_statements, "Max scoped statement executions (0=no limit)", NULL},
    {"max_scope_iterations", (getter)sandbox_get_max_scope_iterations,
     (setter)sandbox_set_max_scope_iterations, "Max scoped iterator steps (0=no limit)", NULL},
    {"max_scope_operations", (getter)sandbox_get_max_scope_operations,
     (setter)sandbox_set_max_scope_operations, "Max scoped SANDBOX_COUNT operations (0=no limit)", NULL},
    /* R/W bool */
    {"allow_float", (getter)sandbox_get_allow_float,
     (setter)sandbox_set_allow_float, "Allow float creation", NULL},
    {"allow_complex", (getter)sandbox_get_allow_complex,
     (setter)sandbox_set_allow_complex, "Allow complex creation", NULL},
    {"allow_dunder_access", (getter)sandbox_get_allow_dunder_access,
     (setter)sandbox_set_allow_dunder_access, "Allow dunder attribute access", NULL},
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
    {"scope_allocation_count", (getter)sandbox_get_scope_allocation_count,
     NULL, "Current scoped allocation count", NULL},
    {"scope_statement_count", (getter)sandbox_get_scope_statement_count,
     NULL, "Current scoped statement count", NULL},
    {"scope_iteration_count", (getter)sandbox_get_scope_iteration_count,
     NULL, "Current scoped iteration count", NULL},
    {"scope_operation_count", (getter)sandbox_get_scope_operation_count,
     NULL, "Current scoped operation count", NULL},
    {"suspended", (getter)sandbox_get_suspended,
     NULL, "True if sandbox is currently suspended", NULL},
    {NULL}  /* Sentinel */
};

/* ============ Methods ============ */

static PyObject *
sandbox_set_limits(_PySandboxObject *self, PyObject *args, PyObject *kwargs)
{
    static char *kwlist[] = {
        "max_int_digits", "max_str_length", "max_bytes_length",
        "max_list_size", "max_dict_size", "max_set_size", "max_tuple_size",
        "max_scope_statements", "max_scope_allocations",
        "max_scope_iterations", "max_scope_operations",
        "allow_float", "allow_complex", "allow_dunder_access", NULL
    };

    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Use sentinel values to detect which kwargs were passed */
    Py_ssize_t max_int_digits = limits->max_int_digits;
    Py_ssize_t max_str_length = limits->max_str_length;
    Py_ssize_t max_bytes_length = limits->max_bytes_length;
    Py_ssize_t max_list_size = limits->max_list_size;
    Py_ssize_t max_dict_size = limits->max_dict_size;
    Py_ssize_t max_set_size = limits->max_set_size;
    Py_ssize_t max_tuple_size = limits->max_tuple_size;
    unsigned long long max_scope_statements = (unsigned long long)limits->scope_max_statements;
    unsigned long long max_scope_allocations = (unsigned long long)limits->scope_max_allocations;
    unsigned long long max_scope_iterations = (unsigned long long)limits->scope_max_iterations;
    unsigned long long max_scope_operations = (unsigned long long)limits->scope_max_operations;
    int allow_float = limits->allow_float;
    int allow_complex = limits->allow_complex;
    int allow_dunder_access = limits->allow_dunder_access;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|nnnnnnnKKKKppp", kwlist,
                                     &max_int_digits, &max_str_length,
                                     &max_bytes_length, &max_list_size,
                                     &max_dict_size, &max_set_size,
                                     &max_tuple_size,
                                     &max_scope_statements, &max_scope_allocations,
                                     &max_scope_iterations, &max_scope_operations,
                                     &allow_float, &allow_complex,
                                     &allow_dunder_access)) {
        return NULL;
    }

    limits->max_int_digits = max_int_digits;
    limits->max_str_length = max_str_length;
    limits->max_bytes_length = max_bytes_length;
    limits->max_list_size = max_list_size;
    limits->max_dict_size = max_dict_size;
    limits->max_set_size = max_set_size;
    limits->max_tuple_size = max_tuple_size;
    limits->scope_max_statements = (uint64_t)max_scope_statements;
    limits->scope_max_allocations = (uint64_t)max_scope_allocations;
    limits->scope_max_iterations = (uint64_t)max_scope_iterations;
    limits->scope_max_operations = (uint64_t)max_scope_operations;
    limits->allow_float = allow_float;
    limits->allow_complex = allow_complex;
    limits->allow_dunder_access = allow_dunder_access;

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
    _PySandboxLimits *limits = &interp->sandbox.limits;

    return Py_BuildValue(
        "{s:n, s:n, s:n, s:n, s:n, s:n, s:n, s:K, s:K, s:K, s:K, s:O, s:O, s:O}",
        "max_int_digits", limits->max_int_digits,
        "max_str_length", limits->max_str_length,
        "max_bytes_length", limits->max_bytes_length,
        "max_list_size", limits->max_list_size,
        "max_dict_size", limits->max_dict_size,
        "max_set_size", limits->max_set_size,
        "max_tuple_size", limits->max_tuple_size,
        "max_scope_statements", (unsigned long long)limits->scope_max_statements,
        "max_scope_allocations", (unsigned long long)limits->scope_max_allocations,
        "max_scope_iterations", (unsigned long long)limits->scope_max_iterations,
        "max_scope_operations", (unsigned long long)limits->scope_max_operations,
        "allow_float", limits->allow_float ? Py_True : Py_False,
        "allow_complex", limits->allow_complex ? Py_True : Py_False,
        "allow_dunder_access", limits->allow_dunder_access ? Py_True : Py_False);
}

static PyObject *
sandbox_get_counts(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandboxLimits *limits = &interp->sandbox.limits;

    return Py_BuildValue(
        "{s:K, s:K, s:K, s:K}",
        "scope_allocation_count", (unsigned long long)limits->scope_allocation_count,
        "scope_statement_count", (unsigned long long)limits->scope_statement_count,
        "scope_iteration_count", (unsigned long long)limits->scope_iteration_count,
        "scope_operation_count", (unsigned long long)limits->scope_operation_count);
}

static PyObject *
sandbox_reset_counts(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    _PySandbox_ResetCounters();
    Py_RETURN_NONE;
}

static PyObject *
sandbox_reset(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    PyInterpreterState *interp = sandbox_get_interp();
    if (interp == NULL) return NULL;
    _PySandbox_Reset(interp);
    Py_RETURN_NONE;
}

static PyObject *
sandbox_enter_scope(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_EnterScope() < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_exit_scope(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    /* Idempotent: no error if not in scope */
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        clear_filenames(&interp->sandbox.limits.registered_filenames);
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
    if (_PySandbox_AddFrameToScope() < 0) {
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
sandbox_clear_filenames(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    _PySandbox_ClearFilenames();
    Py_RETURN_NONE;
}

static PyObject *
sandbox_suspend_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    int result = PySandbox_Suspend();
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromLong(result);
}

static PyObject *
sandbox_resume_method(_PySandboxObject *self, PyObject *Py_UNUSED(args))
{
    int result = PySandbox_Resume();
    if (result < 0) {
        return NULL;
    }
    return PyLong_FromLong(result);
}

static PyObject *
sandbox_freeze(_PySandboxObject *self, PyObject *obj)
{
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

/* _PySandboxScopeContext: __enter__ calls EnterScope, __exit__ calls ExitScope */

typedef struct {
    PyObject_HEAD
} _PySandboxScopeContext;

static PyObject *
scope_ctx_enter(_PySandboxScopeContext *self, PyObject *Py_UNUSED(args))
{
    if (_PySandbox_EnterScope() < 0) {
        return NULL;
    }
    Py_INCREF(self);
    return (PyObject *)self;
}

static PyObject *
scope_ctx_exit(_PySandboxScopeContext *self, PyObject *args)
{
    /* Idempotent exit */
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        clear_filenames(&interp->sandbox.limits.registered_filenames);
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

/* ============ Factory & Reset ============ */

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

void
_PySandbox_Reset(PyInterpreterState *interp)
{
    if (interp == NULL) return;

    _PySandboxLimits *limits = &interp->sandbox.limits;

    /* Reset all limits to 0 */
    limits->max_int_digits = 0;
    limits->max_str_length = 0;
    limits->max_bytes_length = 0;
    limits->max_list_size = 0;
    limits->max_dict_size = 0;
    limits->max_set_size = 0;
    limits->max_tuple_size = 0;
    limits->scope_max_statements = 0;
    limits->scope_max_allocations = 0;
    limits->scope_max_iterations = 0;
    limits->scope_max_operations = 0;

    /* Reset all counters to 0 */
    limits->scope_statement_count = 0;
    limits->scope_allocation_count = 0;
    limits->scope_iteration_count = 0;
    limits->scope_operation_count = 0;

    /* Reset type restrictions to defaults */
    limits->allow_float = 1;
    limits->allow_complex = 1;
    limits->allow_dunder_access = 1;

    /* Reset in_check and suspended */
    limits->in_check = 0;
    limits->suspended = 0;

    /* Clear registered filenames */
    clear_filenames(&limits->registered_filenames);

    /* Clear creation hook */
    Py_CLEAR(interp->sandbox.creation_hook.hook_callback);
    interp->sandbox.creation_hook.hook_func = NULL;
    interp->sandbox.creation_hook.hook_userdata = NULL;
    interp->sandbox.creation_hook.in_hook = 0;

    /* Reset modes */
    interp->sandbox.frozen_mode = 0;
    interp->sandbox.auto_mutable_mode = 0;
    interp->sandbox.opcode_restrict_mode = 0;
    _PySandbox_OpcodeSet_ZERO(&interp->sandbox.banned_opcodes);

    /* Update tracing state */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate != NULL) {
        _PyThreadState_UpdateTracingState(tstate);
    }
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

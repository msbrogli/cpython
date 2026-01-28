/* Sandbox limits: size checks, scoped counters, dunder access, public C API
 *
 * This file contains all limit-checking functions for the sandbox.
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* ============ Size Limit Checks ============ */

int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_int_digits)

    if (ndigits > limits->max_int_digits) {
        /* Prevent recursive checks during error handling */
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, limits->max_int_digits);
        sandbox->suppress_checks = 0;
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
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "String length (%zd) exceeds sandbox limit (%zd)",
                     length, limits->max_str_length);
        sandbox->suppress_checks = 0;
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
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Bytes length (%zd) exceeds sandbox limit (%zd)",
                     length, limits->max_bytes_length);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckListSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_list_size)

    if (size > limits->max_list_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "List size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_list_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckDictSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_dict_size)

    if (size > limits->max_dict_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Dict size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_dict_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckSetSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_set_size)

    if (size > limits->max_set_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Set size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_set_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTupleSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_tuple_size)

    if (size > limits->max_tuple_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Tuple size (%zd) exceeds sandbox limit (%zd)",
                     size, limits->max_tuple_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || sandbox->suspended || sandbox->suppress_checks) {
        return 0;  /* No limits active, suspended, or recursive check */
    }
    _PySandboxLimits *limits = &sandbox->limits;

    /* Fast path: if both types are allowed, nothing to check */
    if (limits->allow_float && limits->allow_complex) {
        return 0;
    }

    /* Scope check */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    /* Check float */
    if (!limits->allow_float && type == &PyFloat_Type) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        sandbox->suppress_checks = 0;
        return -1;
    }

    /* Check complex */
    if (!limits->allow_complex && type == &PyComplex_Type) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}

/* ============ Scoped Allocation Checking ============ */

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
    _PySandboxState *sandbox;
    _PySandboxLimits *limits;

    /* Need to get limits first to check max_allocations */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    int result = sandbox_scope_check_prologue(
        tstate, tstate->interp->sandbox.limits.max_allocations,
        &sandbox, &limits);
    if (result <= 0) {
        return result;
    }

    /* Increment scoped count */
    sandbox->counters.allocation_count++;

    /* If there's already an error set, don't raise another one.
     * This prevents allocation failures during error handling. */
    if (PyErr_Occurred()) {
        return 0;
    }

    /* Check scoped limit */
    /* Hard limit: grace allocations exhausted, fail unconditionally */
    if (sandbox->counters.allocation_count > limits->max_allocations + ALLOCATION_GRACE_HEADROOM) {
        PyErr_SetString(PyExc_SandboxMemoryError, "Sandbox scoped allocation limit exceeded");
        return -1;
    }
    /* Soft limit: raise MemoryError only on the first allocation past the limit */
    if (sandbox->counters.allocation_count == limits->max_allocations + 1) {
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
 * - A statement limit is configured (max_statements > 0)
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
    _PySandboxState *sandbox;
    _PySandboxLimits *limits;

    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    int result = sandbox_scope_check_prologue(
        tstate, tstate->interp->sandbox.limits.max_statements,
        &sandbox, &limits);
    if (result <= 0) {
        return result;
    }

    /* Increment statement count */
    sandbox->counters.statement_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (sandbox->counters.statement_count == limits->max_statements + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox statement limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}

/* ============ Scoped Operation Checking (SANDBOX_COUNT opcode) ============ */

/* _PySandbox_CheckScopeOperation - Check operation execution against limit
 *
 * This function is called from ceval.c for each SANDBOX_COUNT opcode.
 * It only counts operations when:
 * - An operation limit is configured (max_operations > 0)
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
    _PySandboxState *sandbox;
    _PySandboxLimits *limits;

    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    int result = sandbox_scope_check_prologue(
        tstate, tstate->interp->sandbox.limits.max_operations,
        &sandbox, &limits);
    if (result <= 0) {
        return result;
    }

    /* Increment operation count */
    sandbox->counters.operation_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (sandbox->counters.operation_count == limits->max_operations + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}

/* ============ Scoped Iteration Checking ============ */

/* Exported thin wrapper for external callers (e.g. abstract.c) */
int
_PySandbox_CheckIteration(void)
{
    return sandbox_check_iteration();
}

/* ============ Dunder Access Checking ============ */

/* Check if a name starts or ends with "__" (dunder pattern).
 * Uses direct character access to avoid UTF-8 conversion overhead.
 * Returns: 1 if dunder, 0 if not dunder. */
static int
is_dunder_name(PyObject *name)
{
    if (!PyUnicode_Check(name)) {
        return 0;
    }
    Py_ssize_t len = PyUnicode_GET_LENGTH(name);
    if (len < 2) {
        return 0;
    }
    int kind = PyUnicode_KIND(name);
    const void *data = PyUnicode_DATA(name);
    /* Check if starts with "__" */
    if (PyUnicode_READ(kind, data, 0) == '_' &&
        PyUnicode_READ(kind, data, 1) == '_') {
        return 1;
    }
    /* Check if ends with "__" */
    if (len >= 4 &&
        PyUnicode_READ(kind, data, len - 1) == '_' &&
        PyUnicode_READ(kind, data, len - 2) == '_') {
        return 1;
    }
    return 0;
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
    assert(name != NULL);
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }
    _PySandboxLimits *limits = &sandbox->limits;
    if (limits->allow_dunder_access) {
        return 0;
    }

    if (!is_dunder_name(name)) {
        return 0;
    }

    /* Check if in sandbox scope */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL) {
        return 0;
    }
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    /* Block dunder access */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxAttributeError,
                 "dunder attribute access blocked in sandbox: '%U'", name);
    sandbox->suppress_checks = 0;
    return -1;
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
    /* Validate parameters */
    if (max_int_digits < 0) {
        PyErr_SetString(PyExc_ValueError, "max_int_digits cannot be negative");
        return -1;
    }
    if (max_str_length < 0) {
        PyErr_SetString(PyExc_ValueError, "max_str_length cannot be negative");
        return -1;
    }
    if (max_bytes_length < 0) {
        PyErr_SetString(PyExc_ValueError, "max_bytes_length cannot be negative");
        return -1;
    }
    if (max_list_size < 0) {
        PyErr_SetString(PyExc_ValueError, "max_list_size cannot be negative");
        return -1;
    }
    if (max_dict_size < 0) {
        PyErr_SetString(PyExc_ValueError, "max_dict_size cannot be negative");
        return -1;
    }
    if (max_set_size < 0) {
        PyErr_SetString(PyExc_ValueError, "max_set_size cannot be negative");
        return -1;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxState *sandbox = &interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;
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

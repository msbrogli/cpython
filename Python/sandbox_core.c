/* Sandbox core: initialization, scope management, suspend/resume, reset
 *
 * Thread Safety Note:
 * -------------------
 * Sandbox limits and counters are per-interpreter state. In CPython 3.11,
 * the GIL (Global Interpreter Lock) protects all access to interpreter state,
 * so the non-atomic counter increments (allocation_count, etc.) are safe.
 *
 * For Free-Threading (PEP 703) Compatibility:
 * If CPython moves to per-interpreter GILs or free-threading (no-GIL mode),
 * the following operations would need atomic updates:
 *
 *   Counters (in sandbox_limits.c, pycore_sandbox_impl.h):
 *   - sandbox->counters.allocation_count++
 *   - sandbox->counters.statement_count++
 *   - sandbox->counters.iteration_count++
 *   - sandbox->counters.operation_count++
 *
 *   Flags (various files):
 *   - sandbox->suppress_checks reads/writes
 *   - sandbox->suspended reads/writes
 *   - sandbox->creation_hook.in_hook reads/writes
 *
 *   Recommendations for free-threading:
 *   - Use _Py_atomic_int for suppress_checks, suspended, in_hook
 *   - Use _Py_atomic_uint64 for counters
 *   - Add memory barriers for limit comparisons
 *
 * Design Philosophy:
 * The sandbox is designed for single-threaded sandboxed execution where
 * untrusted code runs in isolation. Multi-threaded sandboxed execution
 * within the same interpreter is not a supported use case.
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* ============ Initialization ============ */

/* Forward declaration of the wrapper type - defined in sandbox_iter.c */
extern PyTypeObject _PySandboxIteratorWrapper_Type;

/* Flag indicating whether the wrapper type has been initialized.
 * This is checked by _PySandbox_WrapIterator to avoid using the type
 * before it's ready. The type is initialized lazily on first use because
 * _PySandbox_Init is called too early in interpreter startup (before
 * thread state is available) for PyType_Ready to work. */
int _sandbox_wrapper_type_ready = 0;

/* Initialize the sandbox iterator wrapper type.
 * This must be called lazily, not during _PySandbox_Init, because
 * PyType_Ready requires a valid thread state which isn't available
 * during early interpreter initialization.
 * Returns 0 on success, -1 on error (exception set). */
int
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

    /* Initialize sandbox state using the default macro */
    interp->sandbox = (_PySandboxState)_PySandboxState_INIT;
}

void
_PySandbox_Fini(PyInterpreterState *interp)
{
    /* Free registered filenames set */
    free_filenames(&interp->sandbox.registered_filenames);

    /* Free allowed imports set */
    Py_CLEAR(interp->sandbox.allowed_imports);

    Py_CLEAR(interp->sandbox.creation_hook.hook_callback);
    interp->sandbox.creation_hook.hook_func = NULL;
    interp->sandbox.creation_hook.hook_userdata = NULL;
}

/* ============ Registered Filenames Set ============ */

/* Add a filename to the registered set (creates set lazily) */
int
add_filename_to_set(PyObject **setp, PyObject *filename)
{
    if (!PyUnicode_Check(filename)) {
        PyErr_SetString(PyExc_TypeError, "filename must be a string");
        return -1;
    }

    if (*setp == NULL) {
        *setp = PySet_New(NULL);
        if (*setp == NULL) {
            return -1;
        }
    }

    return PySet_Add(*setp, filename);
}

/* Remove a filename from the registered set */
int
remove_filename_from_set(PyObject *set, PyObject *filename)
{
    if (set == NULL) {
        return 0;
    }
    return PySet_Discard(set, filename);
}

/* Clear all registered filenames (for exit scope) */
void
clear_filenames(PyObject *set)
{
    if (set != NULL) {
        PySet_Clear(set);
    }
}

/* Free the filenames set (for finalization) */
void
free_filenames(PyObject **setp)
{
    Py_CLEAR(*setp);
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

    _PySandboxState *sandbox = &interp->sandbox;

    /* Get current frame and add its filename to registered set */
    _PyInterpreterFrame *frame = get_current_iframe(tstate);
    if (frame == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return -1;
    }

    if (add_filename_to_set(&sandbox->registered_filenames,
                           frame->f_code->co_filename) < 0) {
        return -1;
    }

    /* Reset scope counters */
    sandbox->counters.statement_count = 0;
    sandbox->counters.allocation_count = 0;
    sandbox->counters.iteration_count = 0;
    sandbox->counters.operation_count = 0;

    /* Update tracing state - statement counting requires tracing enabled */
    _PyThreadState_UpdateTracingState(tstate);

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

    _PySandboxState *sandbox = &interp->sandbox;

    /* Clear all registered filenames */
    clear_filenames(sandbox->registered_filenames);

    return 0;
}

int
_PySandbox_IsInScope(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Check if any filenames are registered */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_iframe(NULL);
    if (current == NULL) {
        return 0;
    }

    /* Current frame is in scope if its filename is registered */
    return frame_in_sandbox_scope(sandbox->registered_filenames, current);
}

int
_PySandbox_CheckConfigModification(void)
{
    if (_PySandbox_IsInScope()) {
        PyErr_SetString(PyExc_SandboxSecurityError,
            "Cannot modify sandbox configuration from within sandbox scope");
        return -1;
    }
    return 0;
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

    _PySandboxState *sandbox = &interp->sandbox;

    /* Get current frame */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return -1;
    }

    /* Add current frame's filename to the registered set */
    int result = add_filename_to_set(&sandbox->registered_filenames,
                                     frame->f_code->co_filename);
    if (result == 0) {
        /* Update tracing state - statement counting requires tracing enabled */
        _PyThreadState_UpdateTracingState(tstate);
    }
    return result;
}

/* ============ Filename-Based Scope Management ============ */

int
_PySandbox_AddFilename(PyObject *filename)
{
    assert(filename != NULL);
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }
    PyInterpreterState *interp = tstate->interp;

    int result = add_filename_to_set(&interp->sandbox.registered_filenames, filename);
    if (result == 0) {
        /* Update tracing state - statement counting requires tracing enabled */
        _PyThreadState_UpdateTracingState(tstate);
    }
    return result;
}

int
_PySandbox_RemoveFilename(PyObject *filename)
{
    assert(filename != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    return remove_filename_from_set(interp->sandbox.registered_filenames, filename);
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

    clear_filenames(interp->sandbox.registered_filenames);
}

/* ============ Counter Resetters ============ */

void
_PySandbox_ResetCounters(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.counters.statement_count = 0;
        interp->sandbox.counters.allocation_count = 0;
        interp->sandbox.counters.iteration_count = 0;
        interp->sandbox.counters.operation_count = 0;
    }
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

    _PySandboxState *sandbox = &interp->sandbox;
    if (sandbox->suspended == INT_MAX) {
        PyErr_SetString(PyExc_OverflowError, "Sandbox suspend count overflow");
        return -1;
    }
    sandbox->suspended++;
    return sandbox->suspended;
}

int
PySandbox_Resume(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxState *sandbox = &interp->sandbox;
    if (sandbox->suspended == 0) {
        PyErr_SetString(PyExc_RuntimeError, "Sandbox resume without matching suspend");
        return -1;
    }
    sandbox->suspended--;
    return sandbox->suspended;
}

int
PySandbox_IsSuspended(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;  /* No interpreter means no limits anyway */
    }

    return interp->sandbox.suspended > 0;
}

/* ============ Reset ============ */

void
_PySandbox_Reset(PyInterpreterState *interp)
{
    if (interp == NULL) return;

    _PySandboxState *sandbox = &interp->sandbox;

    /* Clear Python objects before resetting (need proper cleanup) */
    clear_filenames(sandbox->registered_filenames);
    Py_CLEAR(sandbox->creation_hook.hook_callback);
    Py_CLEAR(sandbox->allowed_imports);

    /* Reset limits and counters using default macros */
    sandbox->limits = (_PySandboxLimits)_PySandboxLimits_INIT;
    sandbox->counters = (_PySandboxCounters)_PySandboxCounters_INIT;

    /* Reset creation hook (callback already cleared above) */
    sandbox->creation_hook.hook_func = NULL;
    sandbox->creation_hook.hook_userdata = NULL;
    sandbox->creation_hook.in_hook = 0;

    /* Reset state flags */
    sandbox->suppress_checks = 0;
    sandbox->suspended = 0;

    /* Reset modes */
    sandbox->frozen_mode = 0;
    sandbox->auto_mutable = 0;
    sandbox->opcode_restrict_mode = 0;
    _PySandbox_OpcodeSet_ZERO(&sandbox->banned_opcodes);

    /* Update tracing state */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate != NULL) {
        _PyThreadState_UpdateTracingState(tstate);
    }
}

/* Sandbox Recursion Depth Limiting
 *
 * This module provides per-thread recursion depth tracking for sandboxed code.
 * It counts the number of sandbox-scoped frames currently in the call stack
 * and raises SandboxRecursionError when the limit is exceeded.
 *
 * Key design points:
 * - Per-thread counter stored in PyThreadState (sandbox_recursion_depth)
 * - Only counts frames whose co_filename is in the registered filenames set
 * - Properly handles generators (decrement on yield, increment on resume)
 * - Exception-safe (always decrements on frame exit, including errors)
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"


/* Enter a sandbox-scoped frame.
 * Increments the per-thread recursion depth counter if the frame is in scope.
 * Returns 0 on success, -1 if limit exceeded (exception set).
 */
int
_PySandbox_EnterFrame(_PyInterpreterFrame *frame)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &tstate->interp->sandbox;

    /* Fast path exits */
    if (sandbox->suspended || sandbox->suppress_checks) {
        return 0;
    }
    if (sandbox->limits.max_recursion_depth == 0) {
        return 0;
    }
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    /* Check if frame is in sandbox scope.
     * Unlike other sandbox checks, we check THIS specific frame directly
     * rather than skipping to find the "current executing frame". This is
     * because we're tracking frame entry/exit, not checking the current
     * execution context. */
    if (frame == NULL) {
        return 0;
    }
    int in_scope = filename_is_registered(sandbox->registered_filenames,
                                          frame->f_code->co_filename);
    if (in_scope < 0) {
        return -1;  /* Error during scope check */
    }
    if (!in_scope) {
        return 0;
    }

    /* Increment depth */
    tstate->sandbox_recursion_depth++;

    /* Check limit (use >= max+1 pattern consistent with other sandbox limits) */
    if (tstate->sandbox_recursion_depth >= sandbox->limits.max_recursion_depth + 1) {
        /* Suppress checks during error handling to avoid recursion */
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRecursionError,
                        "Sandbox recursion depth exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}


/* Exit a sandbox-scoped frame.
 * Decrements the per-thread recursion depth counter if the frame was in scope.
 * This must be called on all frame exit paths (return, yield, exception).
 */
void
_PySandbox_ExitFrame(_PyInterpreterFrame *frame)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return;
    }

    _PySandboxState *sandbox = &tstate->interp->sandbox;

    /* Fast path exits - must match EnterFrame conditions */
    if (sandbox->suspended || sandbox->suppress_checks) {
        return;
    }
    if (sandbox->limits.max_recursion_depth == 0) {
        return;
    }
    if (sandbox->registered_filenames == NULL) {
        return;
    }

    /* Check if frame was in sandbox scope.
     * Like EnterFrame, we check THIS specific frame directly. */
    if (frame == NULL) {
        return;
    }
    int in_scope = filename_is_registered(sandbox->registered_filenames,
                                          frame->f_code->co_filename);
    if (in_scope <= 0) {
        /* Not in scope or error - don't decrement */
        return;
    }

    /* Decrement depth with underflow protection.
     * Underflow can happen legitimately when:
     * - Python's native recursion limit fails before our EnterFrame is called
     * - max_recursion_depth was changed between Enter and Exit
     * In these cases, just don't decrement. */
    if (tstate->sandbox_recursion_depth > 0) {
        tstate->sandbox_recursion_depth--;
    }
}

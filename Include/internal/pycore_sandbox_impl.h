/* Sandbox implementation helpers - shared across sandbox_*.c files
 *
 * This header contains static inline helpers and macros used by multiple
 * sandbox source files. It is NOT part of the public API.
 */

#ifndef Py_INTERNAL_SANDBOX_IMPL_H
#define Py_INTERNAL_SANDBOX_IMPL_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "Python.h"
#include "pycore_frame.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"

/* Grace allocation headroom to allow for error handling after limit is hit.
 * This allows Python to format and print MemoryError without cascading failures. */
#define ALLOCATION_GRACE_HEADROOM 1000

/* ============ Thread-safe counter macros ============
 *
 * For GIL-enabled builds (default): use regular increments, protected by the GIL.
 * For free-threading builds (Py_GIL_DISABLED): use atomic operations.
 *
 * Performance notes:
 * - GIL-enabled: zero overhead (plain ++counter)
 * - Free-threading: ~5-10ns overhead per atomic increment (uncontended)
 * This overhead is negligible compared to Python bytecode dispatch (~50-100ns).
 */
#ifdef Py_GIL_DISABLED
/* Free-threading build: use atomic operations */
#  ifdef HAVE_BUILTIN_ATOMIC
#    define _PySandbox_CounterIncrement(counter) \
         __atomic_add_fetch(&(counter), 1, __ATOMIC_RELAXED)
#    define _PySandbox_CounterLoad(counter) \
         __atomic_load_n(&(counter), __ATOMIC_RELAXED)
#  elif defined(_MSC_VER)
#    include <intrin.h>
#    define _PySandbox_CounterIncrement(counter) \
         _InterlockedIncrement64((__int64*)&(counter))
#    define _PySandbox_CounterLoad(counter) \
         _InterlockedCompareExchange64((__int64*)&(counter), 0, 0)
#  else
/* Fallback: volatile operations (not truly atomic but better than nothing) */
#    define _PySandbox_CounterIncrement(counter) \
         (++*((volatile uint64_t*)&(counter)))
#    define _PySandbox_CounterLoad(counter) \
         (*((volatile uint64_t*)&(counter)))
#  endif
#else
/* GIL-enabled build: GIL provides synchronization, use plain operations */
#define _PySandbox_CounterIncrement(counter) (++(counter))
#define _PySandbox_CounterLoad(counter) (counter)
#endif

/* Maximum allowed value for uint64_t limits to prevent overflow when doing
 * comparisons like `count == max + 1` or `count > max + ALLOCATION_GRACE_HEADROOM`.
 * We use UINT64_MAX - ALLOCATION_GRACE_HEADROOM as the safe maximum. */
#define SANDBOX_MAX_LIMIT (UINT64_MAX - ALLOCATION_GRACE_HEADROOM)

/* ============ Inline Helpers ============ */

/* Helper to get current interpreter's sandbox state */
static inline _PySandboxState *
get_sandbox_state(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return NULL;
    }
    return &interp->sandbox;
}

/* Get the current interpreter frame.
 * If tstate is NULL, fetches it via _PyThreadState_GET(). */
static inline _PyInterpreterFrame *
get_current_iframe(PyThreadState *tstate)
{
    if (tstate == NULL) {
        tstate = _PyThreadState_GET();
    }
    if (tstate == NULL || tstate->cframe == NULL) {
        return NULL;
    }
    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    return frame;
}

/* Check if a filename is in the registered set.
 * Uses Python set for O(1) lookup. NULL-safe.
 * Returns: 1 if registered, 0 if not registered, -1 on error (exception set). */
static inline int
filename_is_registered(PyObject *set, PyObject *filename)
{
    if (set == NULL || filename == NULL) {
        return 0;
    }
    /* PySet_Contains returns 1 if found, 0 if not found, -1 on error */
    return PySet_Contains(set, filename);
}

/* Check if current frame is in sandbox scope.
 * A frame is in scope if its co_filename is in the registered set.
 * Returns: 1 if in scope, 0 if not in scope, -1 on error (exception set). */
static inline int
frame_in_sandbox_scope(PyObject *set, _PyInterpreterFrame *frame)
{
    if (set == NULL || PySet_GET_SIZE(set) == 0 || frame == NULL) {
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

/* Helper for scoped counter checks. Performs all early-exit checks:
 * - Thread/interpreter state availability
 * - Suspended or suppress_checks flags
 * - Whether the specific limit is set (max_limit parameter)
 * - Registered filenames and scope check
 *
 * Returns:
 *   1 = proceed with check (sandbox/limits set via out params)
 *   0 = skip check (not in scope, suspended, no limit, etc.)
 *  -1 = error (exception set)
 */
static inline int
sandbox_scope_check_prologue(PyThreadState *tstate,
                             uint64_t max_limit,
                             _PySandboxState **sandbox_out,
                             _PySandboxLimits **limits_out)
{
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &tstate->interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;

    if (sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }
    if (max_limit == 0) {
        return 0;
    }
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_iframe(tstate);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    *sandbox_out = sandbox;
    *limits_out = limits;
    return 1;
}

/* Macro to reduce boilerplate in _PySandbox_Check* functions.
 * Returns 0 (allow) early if:
 * - No interpreter state available
 * - The specific limit is not set (0)
 * - Already in a recursive check
 * - Sandbox is suspended
 * - No filenames registered (not in any scope)
 * - Current frame is not in sandbox scope
 *
 * Optimized to fetch thread state only once.
 */
#define _PYSANDBOX_CHECK_PROLOGUE(limit_field) \
    PyThreadState *_prologue_tstate = _PyThreadState_GET(); \
    if (_prologue_tstate == NULL || _prologue_tstate->interp == NULL) { return 0; } \
    _PySandboxState *sandbox = &_prologue_tstate->interp->sandbox; \
    _PySandboxLimits *limits = &sandbox->limits; \
    if (limits->limit_field == 0 || \
        sandbox->suppress_checks || sandbox->suspended) { \
        return 0; \
    } \
    if (sandbox->registered_filenames == NULL) { \
        return 0; \
    } \
    { \
        _PyInterpreterFrame *_prologue_frame = get_current_iframe(_prologue_tstate); \
        int _in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, _prologue_frame); \
        if (_in_scope < 0) { return -1; } \
        if (!_in_scope) { return 0; } \
    }

/* sandbox_check_iteration - Combined iteration + optional operation check
 *
 * This static inline merges the iteration-limit check and the optional
 * count_iterations_as_operations flag into a single pass so that state
 * loading and scope checking happen only once.  It is inlined into
 * sandbox_iter_wrapper_iternext (the hot path) to eliminate function-call
 * overhead.
 *
 * Called from PyIter_Next() (via the exported wrapper) and from
 * sandbox_iter_wrapper_iternext (inlined).
 *
 * Returns: 0 if OK, -1 if limit exceeded (SandboxRuntimeError set)
 */
static inline int
sandbox_check_iteration(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &tstate->interp->sandbox;
    _PySandboxLimits *limits = &sandbox->limits;

    /* Fast exit: suspended or in recursive check */
    if (sandbox->suppress_checks || sandbox->suspended) {
        return 0;
    }

    int check_iters = (limits->max_iterations > 0);
    int check_ops = (limits->count_iterations_as_operations
                     && limits->max_operations > 0);

    /* Fast exit: nothing to check */
    if (!check_iters && !check_ops) {
        return 0;
    }

    /* Scope check (shared - done once for both counters) */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }
    _PyInterpreterFrame *frame = get_current_iframe(tstate);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    /* Iteration counter */
    if (check_iters) {
        _PySandbox_CounterIncrement(sandbox->counters.iteration_count);
        if (_PySandbox_CounterLoad(sandbox->counters.iteration_count) == limits->max_iterations + 1) {
            sandbox->suppress_checks = 1;
            PyErr_SetString(PyExc_SandboxRuntimeError,
                            "Sandbox iteration limit exceeded");
            sandbox->suppress_checks = 0;
            return -1;
        }
    }

    /* Operation counter (optional, piggybacks on same scope check) */
    if (check_ops) {
        _PySandbox_CounterIncrement(sandbox->counters.operation_count);
        if (_PySandbox_CounterLoad(sandbox->counters.operation_count) == limits->max_operations + 1) {
            sandbox->suppress_checks = 1;
            PyErr_SetString(PyExc_SandboxRuntimeError,
                            "Sandbox operation limit exceeded");
            sandbox->suppress_checks = 0;
            return -1;
        }
    }

    return 0;
}

/* ============ Forward Declarations ============ */

/* Filename set operations (defined in sandbox_core.c) */
extern int add_filename_to_set(PyObject **setp, PyObject *filename);
extern int remove_filename_from_set(PyObject *set, PyObject *filename);
extern void clear_filenames(PyObject *set);
extern void free_filenames(PyObject **setp);

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_SANDBOX_IMPL_H */

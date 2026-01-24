/* Sandbox implementation: resource limits and object creation hooks */

#include "Python.h"
#include "pycore_frame.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "frameobject.h"

/* Forward declarations */
static void free_selected_frames(_PySandboxFrameSet *set);

/* ============ Initialization ============ */

void
_PySandbox_Init(PyInterpreterState *interp)
{
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

    /* Selected frames set (lazy-initialized) */
    interp->sandbox.limits.selected_frames.entries = NULL;
    interp->sandbox.limits.selected_frames.capacity = 0;
    interp->sandbox.limits.selected_frames.count = 0;

    interp->sandbox.limits.allow_float = 1;
    interp->sandbox.limits.allow_complex = 1;
    interp->sandbox.limits.in_check = 0;
    interp->sandbox.limits.suspended = 0;

    interp->sandbox.creation_hook.hook_func = NULL;
    interp->sandbox.creation_hook.hook_userdata = NULL;
    interp->sandbox.creation_hook.hook_callback = NULL;
    interp->sandbox.creation_hook.in_hook = 0;
}

void
_PySandbox_Fini(PyInterpreterState *interp)
{
    /* Free selected frames hash set */
    free_selected_frames(&interp->sandbox.limits.selected_frames);

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

int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_int_digits == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (ndigits > limits->max_int_digits) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_str_length == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (length > limits->max_str_length) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_SetString(PyExc_OverflowError,
                        "String length exceeds sandbox limit");
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckBytesLength(Py_ssize_t length)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_bytes_length == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (length > limits->max_bytes_length) {
        /* Prevent recursive checks during error handling */
        limits->in_check = 1;
        PyErr_SetString(PyExc_OverflowError,
                        "Bytes length exceeds sandbox limit");
        limits->in_check = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckListSize(Py_ssize_t size)
{
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_list_size == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (size > limits->max_list_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_dict_size == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (size > limits->max_dict_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_set_size == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (size > limits->max_set_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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
    _PySandboxLimits *limits = get_sandbox_limits();
    if (limits == NULL || limits->max_tuple_size == 0 ||
        limits->in_check || limits->suspended) {
        return 0;  /* No limit, already checking, or suspended */
    }

    if (size > limits->max_tuple_size) {
        limits->in_check = 1;
        PyErr_Format(PyExc_OverflowError,
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
        PyErr_SetString(PyExc_TypeError,
                        "float type is forbidden in sandbox");
        return -1;
    }

    /* Check complex */
    if (!limits->allow_complex && type == &PyComplex_Type) {
        PyErr_SetString(PyExc_TypeError,
                        "complex type is forbidden in sandbox");
        return -1;
    }

    return 0;
}

/* Grace allocation headroom to allow for error handling after limit is hit.
 * This allows Python to format and print MemoryError without cascading failures. */
#define ALLOCATION_GRACE_HEADROOM 1000

/* Initial capacity for selected frames hash set */
#define SELECTED_FRAMES_INITIAL_CAPACITY 8

/* ============ Selected Frames Hash Set ============ */

/* Hash function for frame pointers - uses pointer value with alignment shift */
static inline size_t
hash_frame_ptr(void *frame, size_t capacity)
{
    uintptr_t addr = (uintptr_t)frame;
    /* Shift off alignment bits (typically 8 bytes) and mask to capacity */
    return (addr >> 3) & (capacity - 1);
}

/* Check if a frame is in the selected frames set. O(1) average case.
 * We store frame+code pairs to guard against frame pointer reuse:
 * when a function returns and its memory is reused for a new frame,
 * the code object will be different, so we won't get false positives. */
static int
frame_is_selected(_PySandboxFrameSet *set, _PyInterpreterFrame *frame)
{
    if (set->entries == NULL || set->count == 0) {
        return 0;
    }

    size_t capacity = set->capacity;
    size_t index = hash_frame_ptr(frame, capacity);

    /* Linear probe for match */
    for (size_t i = 0; i < capacity; i++) {
        _PySandboxFrameEntry *entry = &set->entries[index];
        if (entry->frame == NULL) {
            return 0;  /* Not found - empty slot means not in set */
        }
        if (entry->frame == (void *)frame &&
            entry->code == (void *)frame->f_code) {
            return 1;  /* Found - both frame pointer AND code object match */
        }
        index = (index + 1) & (capacity - 1);
    }
    return 0;  /* Table full without finding - shouldn't happen */
}

/* Initialize the selected frames hash set */
static int
init_selected_frames(_PySandboxFrameSet *set)
{
    if (set->entries == NULL) {
        set->entries = PyMem_RawCalloc(SELECTED_FRAMES_INITIAL_CAPACITY,
                                       sizeof(_PySandboxFrameEntry));
        if (set->entries == NULL) {
            PyErr_NoMemory();
            return -1;
        }
        set->capacity = SELECTED_FRAMES_INITIAL_CAPACITY;
        set->count = 0;
    }
    return 0;
}

/* Grow the selected frames hash set when load factor exceeds threshold */
static int
grow_selected_frames(_PySandboxFrameSet *set)
{
    size_t old_capacity = set->capacity;
    size_t new_capacity = old_capacity * 2;
    _PySandboxFrameEntry *new_entries = PyMem_RawCalloc(new_capacity,
                                                         sizeof(_PySandboxFrameEntry));
    if (new_entries == NULL) {
        PyErr_NoMemory();
        return -1;
    }

    /* Rehash existing entries */
    for (size_t i = 0; i < old_capacity; i++) {
        _PySandboxFrameEntry *old_entry = &set->entries[i];
        if (old_entry->frame != NULL) {
            size_t index = hash_frame_ptr(old_entry->frame, new_capacity);
            while (new_entries[index].frame != NULL) {
                index = (index + 1) & (new_capacity - 1);
            }
            new_entries[index] = *old_entry;
        }
    }

    PyMem_RawFree(set->entries);
    set->entries = new_entries;
    set->capacity = new_capacity;
    return 0;
}

/* Add a frame to the selected frames set */
static int
add_frame_to_set(_PySandboxFrameSet *set, _PyInterpreterFrame *frame)
{
    if (init_selected_frames(set) < 0) {
        return -1;
    }

    /* Check if already in set (idempotent) */
    if (frame_is_selected(set, frame)) {
        return 0;
    }

    /* Grow if load factor would exceed 0.7 */
    if ((set->count + 1) * 10 > set->capacity * 7) {
        if (grow_selected_frames(set) < 0) {
            return -1;
        }
    }

    /* Insert frame+code pair using linear probing */
    size_t capacity = set->capacity;
    size_t index = hash_frame_ptr(frame, capacity);
    while (set->entries[index].frame != NULL) {
        index = (index + 1) & (capacity - 1);
    }
    set->entries[index].frame = (void *)frame;
    set->entries[index].code = (void *)frame->f_code;
    set->count++;

    return 0;
}

/* Clear all frames from the set (for exit scope) */
static void
clear_selected_frames(_PySandboxFrameSet *set)
{
    if (set->entries != NULL) {
        memset(set->entries, 0, set->capacity * sizeof(_PySandboxFrameEntry));
        set->count = 0;
    }
}

/* Free the selected frames set (for finalization) */
static void
free_selected_frames(_PySandboxFrameSet *set)
{
    if (set->entries != NULL) {
        PyMem_RawFree(set->entries);
        set->entries = NULL;
        set->capacity = 0;
        set->count = 0;
    }
}

/* Get the current interpreter frame */
static _PyInterpreterFrame *
get_current_interpreter_frame(void)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return NULL;
    }
    _PyInterpreterFrame *frame = tstate->cframe->current_frame;
    while (frame && _PyFrame_IsIncomplete(frame)) {
        frame = frame->previous;
    }
    return frame;
}

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
     * Current frame must be in the selected_frames set. */
    int in_scope = 0;
    if (limits->selected_frames.count > 0) {
        _PyInterpreterFrame *current = get_current_interpreter_frame();
        if (current != NULL) {
            in_scope = frame_is_selected(&limits->selected_frames, current);
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
            PyErr_NoMemory();
            return -1;
        }
        /* Soft limit: raise MemoryError only on the first allocation past the limit */
        if (limits->global_allocation_count == limits->global_max_allocations + 1) {
            PyErr_NoMemory();
            return -1;
        }
    }

    /* Check scoped limit (if in scope and limit set) */
    if (in_scope && limits->scope_max_allocations > 0) {
        /* Hard limit: grace allocations exhausted, fail unconditionally */
        if (limits->scope_allocation_count > limits->scope_max_allocations + ALLOCATION_GRACE_HEADROOM) {
            PyErr_NoMemory();
            return -1;
        }
        /* Soft limit: raise MemoryError only on the first allocation past the limit */
        if (limits->scope_allocation_count == limits->scope_max_allocations + 1) {
            PyErr_NoMemory();
            return -1;
        }
    }

    return 0;
}

/* ============ Scoped Statement Checking ============ */

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

    /* Skip if no selected frames */
    if (limits->selected_frames.count == 0) {
        return 0;
    }

    /* Check if current frame is in the selected frames set */
    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (current == NULL || !frame_is_selected(&limits->selected_frames, current)) {
        return 0;
    }

    /* Increment statement count */
    limits->scope_statement_count++;

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (limits->scope_statement_count == limits->scope_max_statements + 1) {
        limits->in_check = 1;
        PyErr_SetString(PyExc_RuntimeError,
                        "Sandbox statement limit exceeded");
        limits->in_check = 0;
        return -1;
    }

    return 0;
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

    /* Get current frame and add to selected frames set */
    _PyInterpreterFrame *frame = get_current_interpreter_frame();
    if (frame == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No current frame");
        return -1;
    }

    if (add_frame_to_set(&limits->selected_frames, frame) < 0) {
        return -1;
    }

    /* Reset scope counters */
    limits->scope_statement_count = 0;
    limits->scope_allocation_count = 0;

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

    /* Clear selected frames set */
    clear_selected_frames(&limits->selected_frames);

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

    /* Check if any frames are selected */
    if (limits->selected_frames.count == 0) {
        return 0;
    }

    _PyInterpreterFrame *current = get_current_interpreter_frame();
    if (current == NULL) {
        return 0;
    }

    return frame_is_selected(&limits->selected_frames, current);
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

    /* Add frame to the selected frames set */
    return add_frame_to_set(&limits->selected_frames, frame);
}

/* ============ Counter Resetters ============ */

void
_PySandbox_ResetScopeStatementCount(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.limits.scope_statement_count = 0;
    }
}

void
_PySandbox_ResetScopeAllocationCount(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.limits.scope_allocation_count = 0;
    }
}

void
_PySandbox_ResetGlobalAllocationCount(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.limits.global_allocation_count = 0;
    }
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

#ifndef Py_INTERNAL_SANDBOX_H
#define Py_INTERNAL_SANDBOX_H
#ifdef __cplusplus
extern "C" {
#endif

#ifndef Py_BUILD_CORE
#  error "this header requires Py_BUILD_CORE define"
#endif

#include "pyport.h"        // Py_ssize_t, PyAPI_FUNC
#include "exports.h"       // PyAPI_FUNC

/* Forward declarations */
typedef struct _object PyObject;
typedef struct _typeobject PyTypeObject;
typedef struct _is PyInterpreterState;
struct _frame;

/*
 * Sandbox Limits and Object Creation Hooks
 *
 * This module provides mechanisms for sandboxing Python code:
 * 1. Resource limits (integer size, string length, container size)
 * 2. Object creation hooks (intercept and optionally replace objects)
 * 3. Type restrictions (e.g., forbid float creation)
 */

/* Sandbox limits structure - stored in PyInterpreterState */
typedef struct {
    /* Integer limits: max number of internal digits (each ~30 bits) */
    /* Set to 0 to disable limit */
    Py_ssize_t max_int_digits;

    /* String/bytes limits: max length in characters/bytes */
    Py_ssize_t max_str_length;
    Py_ssize_t max_bytes_length;

    /* Container limits: max number of items */
    Py_ssize_t max_list_size;
    Py_ssize_t max_dict_size;
    Py_ssize_t max_set_size;
    Py_ssize_t max_tuple_size;

    /* Allocation limits: count of GC-tracked object allocations */
    uint64_t max_allocations;   /* 0 = no limit */
    uint64_t allocation_count;  /* Current count */

    /* Type restrictions */
    int allow_float;         /* 0 = forbidden, 1 = allowed (default) */
    int allow_complex;       /* 0 = forbidden, 1 = allowed (default) */

    /* Recursion prevention - nonzero during limit check (to avoid recursive
       checks when error handling creates strings/integers) */
    int in_check;

    /* Suspend counter - when > 0, all limits are bypassed.
       Use PySandbox_Suspend/Resume for nested suspend/resume. */
    int suspended;
} _PySandboxLimits;

/* Default values (no limits) */
#define _PySandboxLimits_INIT { \
    .max_int_digits = 0,        \
    .max_str_length = 0,        \
    .max_bytes_length = 0,      \
    .max_list_size = 0,         \
    .max_dict_size = 0,         \
    .max_set_size = 0,          \
    .max_tuple_size = 0,        \
    .max_allocations = 0,       \
    .allocation_count = 0,      \
    .allow_float = 1,           \
    .allow_complex = 1,         \
    .in_check = 0,              \
    .suspended = 0,             \
}

/* Object creation hook flags */
#define Py_OBJHOOK_TYPE_CALL  0x01  /* Called from type_call - can replace */
#define Py_OBJHOOK_INIT       0x02  /* Called from _PyObject_Init - observe only */

/* Object creation hook function signature
 *
 * Parameters:
 *   obj: The object being created
 *   type: The type of the object
 *   frame: Current frame (may be NULL)
 *   flags: Py_OBJHOOK_TYPE_CALL or Py_OBJHOOK_INIT
 *   userdata: User-provided data pointer
 *
 * Returns:
 *   - Replacement object (new reference): replaces obj (only if TYPE_CALL flag)
 *   - Py_None (new reference): keep original object
 *   - NULL: error occurred, exception should be set
 */
typedef PyObject* (*Py_ObjectCreationHookFunc)(
    PyObject *obj,
    PyTypeObject *type,
    struct _frame *frame,
    int flags,
    void *userdata
);

/* Object creation hook state - stored in PyInterpreterState */
typedef struct {
    /* C-level hook */
    Py_ObjectCreationHookFunc hook_func;
    void *hook_userdata;

    /* Python-level callback (wrapped by trampoline) */
    PyObject *hook_callback;

    /* Recursion prevention - nonzero means we're inside a hook */
    int in_hook;
} _PyObjectCreationHook;

#define _PyObjectCreationHook_INIT { \
    .hook_func = NULL,               \
    .hook_userdata = NULL,           \
    .hook_callback = NULL,           \
    .in_hook = 0,                    \
}

/* Combined sandbox state */
typedef struct {
    _PySandboxLimits limits;
    _PyObjectCreationHook creation_hook;
} _PySandboxState;

#define _PySandboxState_INIT {              \
    .limits = _PySandboxLimits_INIT,        \
    .creation_hook = _PyObjectCreationHook_INIT, \
}

/* ============ Internal API ============ */

/* Check integer size against limits. Returns 0 if OK, -1 if exceeded (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckIntSize(Py_ssize_t ndigits);

/* Check string length against limits. Returns 0 if OK, -1 if exceeded (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckStrLength(Py_ssize_t length);

/* Check bytes length against limits. Returns 0 if OK, -1 if exceeded (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckBytesLength(Py_ssize_t length);

/* Check container size against limits. Returns 0 if OK, -1 if exceeded (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckListSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckDictSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckSetSize(Py_ssize_t size);
PyAPI_FUNC(int) _PySandbox_CheckTupleSize(Py_ssize_t size);

/* Check if a type is allowed. Returns 0 if allowed, -1 if forbidden (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckTypeAllowed(PyTypeObject *type);

/* Check allocation count against limits. Returns 0 if OK, -1 if exceeded (sets exception) */
PyAPI_FUNC(int) _PySandbox_CheckAllocation(void);

/* Call object creation hook. Returns new object (may be replacement) or NULL on error */
PyAPI_FUNC(PyObject *) _PySandbox_CallCreationHook(
    PyObject *obj,
    PyTypeObject *type,
    int flags
);

/* Initialize/finalize sandbox state for an interpreter */
PyAPI_FUNC(void) _PySandbox_Init(PyInterpreterState *interp);
PyAPI_FUNC(void) _PySandbox_Fini(PyInterpreterState *interp);

/* ============ Public C API ============ */

/* Set sandbox limits. Returns 0 on success, -1 on error */
PyAPI_FUNC(int) PySandbox_SetLimits(
    Py_ssize_t max_int_digits,
    Py_ssize_t max_str_length,
    Py_ssize_t max_bytes_length,
    Py_ssize_t max_list_size,
    Py_ssize_t max_dict_size,
    Py_ssize_t max_set_size,
    int allow_float
);

/* Get current sandbox limits */
PyAPI_FUNC(void) PySandbox_GetLimits(
    Py_ssize_t *max_int_digits,
    Py_ssize_t *max_str_length,
    Py_ssize_t *max_bytes_length,
    Py_ssize_t *max_list_size,
    Py_ssize_t *max_dict_size,
    Py_ssize_t *max_set_size,
    int *allow_float
);

/* Set object creation hook. Pass NULL to disable. Returns 0 on success */
PyAPI_FUNC(int) PySandbox_SetCreationHook(
    Py_ObjectCreationHookFunc hook,
    void *userdata
);

/* Get current object creation hook */
PyAPI_FUNC(Py_ObjectCreationHookFunc) PySandbox_GetCreationHook(void **userdata);

/* Suspend/resume sandbox limits.
 * Use these in trusted code (e.g., syscalls) to temporarily bypass limits.
 * Calls can be nested - limits are only active when suspend count is 0.
 * Returns the new suspend count, or -1 on error. */
PyAPI_FUNC(int) PySandbox_Suspend(void);
PyAPI_FUNC(int) PySandbox_Resume(void);

/* Check if sandbox limits are currently suspended */
PyAPI_FUNC(int) PySandbox_IsSuspended(void);

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_SANDBOX_H */

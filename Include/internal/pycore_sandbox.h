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
#include <string.h>        // memset

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
 *
 * == Important Implementation Details ==
 *
 * Single-Raise Behavior (Iteration/Operation Limits):
 *   These limits only raise an error ONCE, at count == max+1.
 *   Subsequent operations beyond the limit do NOT raise additional errors.
 *   This prevents cascading failures during error handling when Python
 *   needs to execute statements to format and display the exception.
 *
 * Overflow Protection:
 *   All uint64_t limits (max_iterations, max_operations) are capped at
 *   SANDBOX_MAX_LIMIT = UINT64_MAX - 1000. This ensures that comparisons
 *   like `count == max + 1` cannot overflow.
 *
 * Thread Safety:
 *   The sandbox relies on the GIL for thread safety. Non-atomic counter
 *   increments and flag manipulations are safe under the current GIL model.
 *   For free-threading (no-GIL) builds, atomic operations would be needed.
 */

/* Forward declaration for interpreter frame */
struct _PyInterpreterFrame;

/* 256-bit bitmap for opcode restriction. Bit set = opcode banned. */
typedef struct {
    uint32_t bits[8];  /* 8 * 32 = 256 bits */
} _PySandboxOpcodeSet;

#define _PySandbox_OpcodeSet_HAS(set, op) \
    ((set)->bits[(op) >> 5] & (1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_SET(set, op) \
    ((set)->bits[(op) >> 5] |= (1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_CLEAR(set, op) \
    ((set)->bits[(op) >> 5] &= ~(1U << ((op) & 31)))
#define _PySandbox_OpcodeSet_ZERO(set) \
    memset((set)->bits, 0, sizeof((set)->bits))

/* Sandbox limits structure - stored in PyInterpreterState */
typedef struct {
    /* Integer limits: max number of internal digits.
     * Each internal digit stores ~30 bits (PyLong_SHIFT), which is
     * approximately 9 decimal digits. For example:
     *   - max_int_digits=5 allows integers up to ~10^45
     *   - max_int_digits=100 allows integers up to ~10^900
     * Set to 0 to disable limit. */
    Py_ssize_t max_int_digits;

    /* String/bytes limits: max length in characters/bytes */
    Py_ssize_t max_str_length;
    Py_ssize_t max_bytes_length;

    /* Container limits: max number of items */
    Py_ssize_t max_list_size;
    Py_ssize_t max_dict_size;
    Py_ssize_t max_set_size;
    Py_ssize_t max_tuple_size;

    /* Scoped limits - only enforced within sandbox scope (selected frames) */
    uint64_t max_iterations;      /* 0 = no limit */
    uint64_t max_operations;      /* 0 = no limit */
    uint64_t max_recursion_depth; /* 0 = no limit */

    /* Type restrictions */
    int allow_float;         /* 0 = forbidden, 1 = allowed (default) */
    int allow_complex;       /* 0 = forbidden, 1 = allowed (default) */

    /* Allow access to dunder attributes (names containing __) */
    int allow_dunder_access;     /* 1 = allowed (default), 0 = block __ attributes */

    /* Count iterator yields as operations towards max_operations */
    int count_iterations_as_operations;  /* 0 = off (default), 1 = each yield increments operation_count */

    /* Block unsafe operations: compile(), __iter__(), gc introspection.
     * When allow_unsafe=0 (default), these are blocked in sandbox scope.
     * Set allow_unsafe=1 to allow them (less secure). */
    int allow_unsafe;

    /* Allow I/O operations (file, socket, raw fd).
     * When allow_io=0 (default), I/O is blocked in sandbox scope.
     * Set allow_io=1 to allow I/O (less secure). */
    int allow_io;

    /* Import restrictions */
    int import_restrict_mode;     /* 0 = off, 1 = enforce allowed_imports (default) */
    int import_allow_submodules;  /* 1 = allow submodules, 0 = deny (default) */

    /* Module access restriction mode.
     * When module_access_restrict_mode=1, only modules in allowed_modules can be accessed.
     * When module_access_restrict_mode=0 (default), all modules can be accessed. */
    int module_access_restrict_mode;

    /* Allow submodules when parent is allowed.
     * When allow_submodules=1 (default), allowing 'xml' also allows 'xml.etree.ElementTree'.
     * When allow_submodules=0, only exact module names in allowed_modules are allowed. */
    int allow_submodules;
} _PySandboxLimits;

/* Sandbox counters - separated from limits for clarity */
typedef struct {
    uint64_t iteration_count;     /* Iterator calls in scope */
    uint64_t operation_count;     /* Counted operations (SANDBOX_COUNT opcode) in scope */
} _PySandboxCounters;

/* Default values (no limits) */
#define _PySandboxLimits_INIT { \
    .max_int_digits = 0,            \
    .max_str_length = 0,            \
    .max_bytes_length = 0,          \
    .max_list_size = 0,             \
    .max_dict_size = 0,             \
    .max_set_size = 0,              \
    .max_tuple_size = 0,            \
    .max_iterations = 0,            \
    .max_operations = 0,            \
    .max_recursion_depth = 0,       \
    .allow_float = 1,               \
    .allow_complex = 1,             \
    .allow_dunder_access = 1,       \
    .count_iterations_as_operations = 0, \
    .allow_unsafe = 0,              \
    .allow_io = 0,                  \
    .import_restrict_mode = 1,      \
    .import_allow_submodules = 0,   \
    .module_access_restrict_mode = 1, \
    .allow_submodules = 1,          \
}

#define _PySandboxCounters_INIT { \
    .iteration_count = 0,           \
    .operation_count = 0,           \
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
    _PySandboxCounters counters;
    _PyObjectCreationHook creation_hook;
    int frozen_mode;  /* 1 = global freeze active (block all attr mutations), 0 = normal */
    int auto_mutable;  /* 1 = auto-mark created objects as mutable within scope, 0 = off */
    int opcode_restrict_mode;            /* 1 = active, 0 = off */
    _PySandboxOpcodeSet banned_opcodes;  /* bitmap of banned opcodes */

    /* Sandbox scope tracking - Python set of registered filenames.
     * Code with a registered co_filename counts toward scope limits.
     * This is simpler than frame-based tracking and works reliably
     * across function calls within the same code context.
     * NULL when no filenames are registered (lazy-initialized). */
    PyObject *registered_filenames;

    /* Import allowlist - Python set of tuples (module_name, import_name).
     * Only checked when import_restrict_mode=1 and in sandbox scope.
     * NULL or empty set means no imports allowed when mode is active. */
    PyObject *allowed_imports;

    /* Allowed modules - Python frozenset of module names (strings).
     * When set (non-NULL), only modules in this set can be accessed in sandbox scope.
     * NULL = all modules allowed (no restriction).
     * This provides defense in depth even if attacker has a module reference.
     * Stored as frozenset for O(1) getter performance. */
    PyObject *allowed_modules;

    /* Side tables for frozen mode (avoids per-object ob_flags ABI change).
     * mutable_objects: set of objects allowed to be mutated in frozen mode.
     * frozen_objects: set of individually frozen objects.
     * Uses weak references where possible, allowing tracked objects to be
     * garbage collected. Objects that don't support weak references (e.g.,
     * built-in type instances) fall back to strong references.
     * NULL when not in use (lazy-initialized). */
    PyObject *mutable_objects;
    PyObject *frozen_objects;

    /* Recursion prevention - nonzero during limit check (to avoid recursive
       checks when error handling creates strings/integers) */
    int suppress_checks;

    /* Suspend counter - when > 0, all limits are bypassed.
       Use PySandbox_Suspend/Resume for nested suspend/resume. */
    int suspended;

    /* Master enable flag. 0=disabled (default), 1=active.
       When disabled, sandbox limits are not enforced even if configured. */
    int enabled;
} _PySandboxState;

#define _PySandboxState_INIT {              \
    .limits = _PySandboxLimits_INIT,        \
    .counters = _PySandboxCounters_INIT,    \
    .creation_hook = _PyObjectCreationHook_INIT, \
    .frozen_mode = 0,                       \
    .auto_mutable = 0,                 \
    .opcode_restrict_mode = 0,              \
    .banned_opcodes = {{0}},                \
    .registered_filenames = NULL,           \
    .allowed_imports = NULL,                \
    .allowed_modules = NULL,                \
    .mutable_objects = NULL,                \
    .frozen_objects = NULL,                 \
    .suppress_checks = 0,                          \
    .suspended = 0,                         \
    .enabled = 0,                           \
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

/* Scoped operation checking (SANDBOX_COUNT opcode) - returns -1 and sets exception when limit exceeded */
PyAPI_FUNC(int) _PySandbox_CheckScopeOperation(void);

/* Scoped operation checking with count parameter (for folded operations) */
PyAPI_FUNC(int) _PySandbox_CheckScopeOperationN(int count);

/* Scoped iteration checking - returns -1 and sets exception when limit exceeded.
 * This is the exported version; sandbox.c uses a static inline for internal callers. */
PyAPI_FUNC(int) _PySandbox_CheckIteration(void);

/* Check dunder attribute access - returns -1 and sets exception when blocked */
PyAPI_FUNC(int) _PySandbox_CheckDunderAccess(PyObject *name);

/* Check if an unsafe operation is blocked in sandbox scope.
 * Returns 0 if allowed, -1 if blocked (sets SandboxSecurityError).
 * Unsafe operations include: compile(), __iter__() access, gc introspection. */
PyAPI_FUNC(int) _PySandbox_CheckUnsafeBlocked(const char *operation);

/* Check if I/O operations are blocked in sandbox scope.
 * Returns 0 if allowed, -1 if blocked (sets SandboxSecurityError).
 * I/O operations include: file open, socket, raw fd operations. */
PyAPI_FUNC(int) _PySandbox_CheckIOAllowed(const char *operation);

/* Check if attribute mutation is blocked on an object.
 * Returns 0 if mutation is allowed, -1 if blocked (sets SandboxAttributeError).
 * Checks: mutable_objects set (fast exit), frozen_objects set, global frozen_mode.
 * Respects sandbox suspend state. Uses side tables to avoid ABI changes. */
PyAPI_FUNC(int) _PySandbox_CheckFrozen(PyObject *obj);

/* Auto-mutable: add a newly created object to the mutable_objects set
 * if auto_mutable and frozen_mode are both active and the current frame
 * is in sandbox scope. This is a no-op when either flag is off or the
 * frame is out of scope. */
PyAPI_FUNC(void) _PySandbox_MaybeMarkMutable(PyObject *obj);

/* Opcode restriction check - called from DO_TRACING in ceval.c.
 * Returns 0 if opcode is allowed, -1 if banned (sets SandboxRuntimeError).
 * Fast exits: mode off, suspended, suppress_checks, not in scope, opcode not banned. */
PyAPI_FUNC(int) _PySandbox_CheckOpcode(int opcode);

/* Check if import is allowed. Returns 0 if allowed, -1 if blocked.
 * abs_name: fully resolved module name
 * fromlist: tuple of names being imported, or NULL for bare import */
PyAPI_FUNC(int) _PySandbox_CheckImport(PyObject *abs_name, PyObject *fromlist);

/* Set the import allowlist. Accepts iterable of (module, name) tuples.
 * Returns 0 on success, -1 on error. */
PyAPI_FUNC(int) PySandbox_SetAllowedImports(PyObject *modules);

/* Get the import allowlist. Returns a new reference to a frozenset,
 * or NULL on error. */
PyAPI_FUNC(PyObject *) PySandbox_GetAllowedImports(void);

/* Check if accessing a module is allowed.
 * Returns 0 if allowed, -1 if blocked (sets SandboxSecurityError).
 * Called from module_getattro() before attribute access.
 * When module_access_restrict_mode=1, checks if module is in allowed_modules. */
PyAPI_FUNC(int) _PySandbox_CheckModuleAccess(PyObject *module);

/* Sandbox recursion depth tracking */
PyAPI_FUNC(int) _PySandbox_EnterFrame(struct _PyInterpreterFrame *frame);  /* Check/increment depth on frame entry */
PyAPI_FUNC(void) _PySandbox_ExitFrame(struct _PyInterpreterFrame *frame);  /* Decrement depth on frame exit */

/* Sandbox scope management */
PyAPI_FUNC(int) _PySandbox_EnterScope(void);   /* Set current frame as entry, reset scope counters */
PyAPI_FUNC(int) _PySandbox_ExitScope(void);    /* Clear entry frame and selected frames */
PyAPI_FUNC(int) _PySandbox_IsInScope(void);    /* Check if currently in sandbox scope */
PyAPI_FUNC(int) _PySandbox_AddFrameToScope(void);  /* Add current frame's filename to registered set */

/* Security check for configuration modification.
 * Returns 0 if modification allowed, -1 if blocked (sets SandboxSecurityError).
 * This prevents code running in sandbox scope from modifying sandbox config. */
PyAPI_FUNC(int) _PySandbox_CheckConfigModification(void);

/* Filename-based scope management */
PyAPI_FUNC(int) _PySandbox_AddFilename(PyObject *filename);      /* Add a filename to the scope set */
PyAPI_FUNC(int) _PySandbox_RemoveFilename(PyObject *filename);   /* Remove a filename from the set */
PyAPI_FUNC(void) _PySandbox_ClearFilenames(void);                /* Clear all registered filenames */

/* Counter resetter - resets all scope counters */
PyAPI_FUNC(void) _PySandbox_ResetCounters(void);

/* Call object creation hook. Returns new object (may be replacement) or NULL on error */
PyAPI_FUNC(PyObject *) _PySandbox_CallCreationHook(
    PyObject *obj,
    PyTypeObject *type,
    int flags
);

/* Initialize/finalize sandbox state for an interpreter */
PyAPI_FUNC(void) _PySandbox_Init(PyInterpreterState *interp);
PyAPI_FUNC(void) _PySandbox_Fini(PyInterpreterState *interp);

/* ============ Iterator Wrapper ============ */

/* Sandbox iterator wrapper type - wraps iterators to check limits on each step */
PyAPI_DATA(PyTypeObject) _PySandboxIteratorWrapper_Type;

/* Wrap an iterator if sandbox scope is active.
 * Returns a new reference (either the wrapper or the original iterator with incref).
 * Returns NULL on error. */
PyAPI_FUNC(PyObject *) _PySandbox_WrapIterator(PyObject *iter);

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

/* Enable/disable the sandbox (primary control).
 * When disabled (default), sandbox limits are not enforced even if configured.
 * Enable must be called to activate sandbox enforcement. */
PyAPI_FUNC(void) PySandbox_Enable(void);
PyAPI_FUNC(void) PySandbox_Disable(void);
PyAPI_FUNC(int) PySandbox_IsEnabled(void);

/* Suspend/resume sandbox limits.
 * Use these in trusted code (e.g., syscalls) to temporarily bypass limits.
 * Calls can be nested - limits are only active when suspend count is 0.
 * Returns the new suspend count, or -1 on error. */
PyAPI_FUNC(int) PySandbox_Suspend(void);
PyAPI_FUNC(int) PySandbox_Resume(void);

/* Check if sandbox limits are currently suspended */
PyAPI_FUNC(int) PySandbox_IsSuspended(void);

/* Set/get global frozen mode. When active, all attribute mutations are blocked
 * unless the target object is in the mutable_objects set. */
PyAPI_FUNC(void) PySandbox_SetFrozenMode(int mode);
PyAPI_FUNC(int) PySandbox_GetFrozenMode(void);

/* Freeze a specific object (add to frozen_objects set) */
PyAPI_FUNC(void) PySandbox_FreezeObject(PyObject *obj);

/* Check if a specific object is frozen (in frozen_objects set) */
PyAPI_FUNC(int) PySandbox_IsObjectFrozen(PyObject *obj);

/* Mark an object as mutable (override frozen mode).
 * If mutable is nonzero, adds to mutable_objects set; otherwise removes. */
PyAPI_FUNC(void) PySandbox_SetObjectMutable(PyObject *obj, int mutable);

/* Set/get auto-mutable mode. When enabled alongside frozen mode,
 * newly created functions, classes, and instances within sandbox scope
 * are automatically added to the mutable_objects set. */
PyAPI_FUNC(void) PySandbox_SetAutoMutableMode(int mode);
PyAPI_FUNC(int) PySandbox_GetAutoMutableMode(void);

/* Opcode restriction mode: enable/disable runtime opcode checks.
 * When enabled, opcodes in the banned set raise SandboxRuntimeError
 * for code executing within sandbox scope.
 * Must call _PyThreadState_UpdateTracingState after changing. */
PyAPI_FUNC(void) PySandbox_SetOpcodeRestrictMode(int mode);
PyAPI_FUNC(int) PySandbox_GetOpcodeRestrictMode(void);

/* Set/get the banned opcodes bitmap.
 * SetBannedOpcodes: accepts a Python set/frozenset of ints, or None to clear.
 * GetBannedOpcodes: returns a new frozenset of banned opcode ints. */
PyAPI_FUNC(int) PySandbox_SetBannedOpcodes(PyObject *opcode_set);
PyAPI_FUNC(PyObject *) PySandbox_GetBannedOpcodes(void);

/* ============ sys.sandbox namespace object ============ */

/* Create the sys.sandbox singleton object (_PySandboxObject type).
 * Returns a new reference. */
PyAPI_FUNC(PyObject *) _PySandbox_NewObject(void);

/* Reset all sandbox state to defaults (limits, counters, modes, scope, hooks). */
PyAPI_FUNC(void) _PySandbox_Reset(PyInterpreterState *interp);

#ifdef __cplusplus
}
#endif
#endif /* !Py_INTERNAL_SANDBOX_H */

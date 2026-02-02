/* Sandbox limits: size checks, scoped counters, dunder access, public C API
 *
 * This file contains all limit-checking functions for the sandbox.
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"
#include "pycore_code.h"  /* For CO_CLASS_BODY */

/* ============ Size Limit Checks ============ */

int
_PySandbox_CheckIntSize(Py_ssize_t ndigits)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_int_digits)

    if (ndigits > config->max_int_digits) {
        /* Prevent recursive checks during error handling */
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Integer size (%zd digits) exceeds sandbox limit (%zd digits)",
                     ndigits, config->max_int_digits);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckStrLength(Py_ssize_t length)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_str_length)

    if (length > config->max_str_length) {
        /* Prevent recursive checks during error handling */
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "String length (%zd) exceeds sandbox limit (%zd)",
                     length, config->max_str_length);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckBytesLength(Py_ssize_t length)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_bytes_length)

    if (length > config->max_bytes_length) {
        /* Prevent recursive checks during error handling */
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Bytes length (%zd) exceeds sandbox limit (%zd)",
                     length, config->max_bytes_length);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckListSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_list_size)

    if (size > config->max_list_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "List size (%zd) exceeds sandbox limit (%zd)",
                     size, config->max_list_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckDictSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_dict_size)

    if (size > config->max_dict_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Dict size (%zd) exceeds sandbox limit (%zd)",
                     size, config->max_dict_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckSetSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_set_size)

    if (size > config->max_set_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Set size (%zd) exceeds sandbox limit (%zd)",
                     size, config->max_set_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTupleSize(Py_ssize_t size)
{
    _PYSANDBOX_CHECK_PROLOGUE(max_tuple_size)

    if (size > config->max_tuple_size) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxOverflowError,
                     "Tuple size (%zd) exceeds sandbox limit (%zd)",
                     size, config->max_tuple_size);
        sandbox->suppress_checks = 0;
        return -1;
    }
    return 0;
}

int
_PySandbox_CheckTypeAllowed(PyTypeObject *type)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;  /* No sandbox state or not enforced */
    }
    _PySandboxConfig *config = &sandbox->config;

    /* Fast path: if both types are allowed, nothing to check */
    if (config->allow_float && config->allow_complex) {
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

    if (!config->allow_float && PyType_IsSubtype(type, &PyFloat_Type)) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "float type is forbidden in sandbox");
        sandbox->suppress_checks = 0;
        return -1;
    }

    if (!config->allow_complex && PyType_IsSubtype(type, &PyComplex_Type)) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxTypeError,
                        "complex type is forbidden in sandbox");
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
    _PySandboxConfig *config;

    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    int result = sandbox_scope_check_prologue(
        tstate, tstate->interp->sandbox.config.max_operations,
        &sandbox, &config);
    if (result <= 0) {
        return result;
    }

    /* Increment operation count */
    _PySandbox_CounterIncrement(sandbox->counters.operation_count);

    /* Check limit - only raise error ONCE at exactly max+1 to allow error handling */
    if (_PySandbox_CounterLoad(sandbox->counters.operation_count) >= config->max_operations + 1) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxRuntimeError,
                        "Sandbox operation limit exceeded");
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}

/* _PySandbox_CheckScopeOperationN - Check N operations against limit
 *
 * Like _PySandbox_CheckScopeOperation, but increments counter by N instead of 1.
 * Used by SANDBOX_COUNT opcode when operations were folded during AST optimization.
 *
 * Parameters:
 *   count: Number of operations to count (must be >= 1)
 *
 * Returns: 0 if OK, -1 if limit exceeded (RuntimeError set)
 */
int
_PySandbox_CheckScopeOperationN(int count)
{
    _PySandboxState *sandbox;
    _PySandboxConfig *config;

    if (count <= 0) {
        return 0;  /* No-op for count <= 0 */
    }

    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    int result = sandbox_scope_check_prologue(
        tstate, tstate->interp->sandbox.config.max_operations,
        &sandbox, &config);
    if (result <= 0) {
        return result;
    }

    /* Increment operation count by N */
    _PySandbox_CounterAdd(sandbox->counters.operation_count, count);

    /* Check limit - only raise error ONCE when crossing max to allow error handling */
    if (_PySandbox_CounterLoad(sandbox->counters.operation_count) >= config->max_operations + 1) {
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

/* Check if name is "__iter__"
 * Returns: 1 if __iter__, 0 otherwise. */
static int
is_iter_dunder(PyObject *name)
{
    if (!PyUnicode_Check(name)) {
        return 0;
    }
    return _PyUnicode_EqualToASCIIString(name, "__iter__");
}

/* Whitelist of dunders allowed in class body when allow_class_creation=1.
 * These are needed for class creation machinery to function:
 * - __name__: injected by compiler for class body
 * - __module__: set by class body
 * - __qualname__: set by class body
 * - __annotations__: for annotated class variables
 * - __doc__: docstrings
 * - __classcell__: for super() support
 * - __slots__: slot definitions
 * Returns: 1 if whitelisted, 0 otherwise. */
static int
is_class_body_safe_dunder(PyObject *name)
{
    return (_PyUnicode_EqualToASCIIString(name, "__name__") ||
            _PyUnicode_EqualToASCIIString(name, "__module__") ||
            _PyUnicode_EqualToASCIIString(name, "__qualname__") ||
            _PyUnicode_EqualToASCIIString(name, "__annotations__") ||
            _PyUnicode_EqualToASCIIString(name, "__doc__") ||
            _PyUnicode_EqualToASCIIString(name, "__classcell__") ||
            _PyUnicode_EqualToASCIIString(name, "__slots__"));
}

/* _PySandbox_CheckDunderAccess - Check if dunder attribute access is blocked
 *
 * This function is called from ceval.c for LOAD_ATTR, STORE_ATTR, DELETE_ATTR.
 * It blocks access to:
 * - __iter__ when allow_unsafe=0
 * - All dunder attributes when allow_dunder_access=0
 *
 * Special handling for class body context:
 * - When allow_class_creation=1 and in a class body (CO_CLASS_BODY flag),
 *   certain dunders needed for class creation are whitelisted.
 *
 * Requirements for blocking:
 * - Sandbox is not suspended and not in recursive check
 * - At least one filename is registered for scope tracking
 * - Current frame's co_filename matches a registered filename
 *
 * Returns: 0 if access allowed, -1 if blocked (exception set)
 */
int
_PySandbox_CheckDunderAccess(PyObject *name)
{
    assert(name != NULL);
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }
    _PySandboxConfig *config = &sandbox->config;

    /* Fast path: if both __iter__ and general dunder access are allowed, skip */
    int check_iter = !config->allow_unsafe && is_iter_dunder(name);
    int check_dunder = !config->allow_dunder_access && is_dunder_name(name);

    if (!check_iter && !check_dunder) {
        return 0;
    }

    /* Check if in sandbox scope (shared by both checks) */
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

    /* Block __iter__ access unless allow_unsafe */
    if (check_iter) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxSecurityError,
                        "__iter__ access is not allowed in sandbox scope");
        sandbox->suppress_checks = 0;
        return -1;
    }

    /* Check class body whitelist before blocking general dunder access.
     * When allow_class_creation=1 and we're in a class body (CO_CLASS_BODY flag),
     * allow certain dunders needed for class creation machinery. */
    if (check_dunder && config->allow_class_creation) {
        if (frame->f_code != NULL &&
            (frame->f_code->co_flags & CO_CLASS_BODY)) {
            if (is_class_body_safe_dunder(name)) {
                return 0;  /* Allow this dunder in class body */
            }
        }
    }

    /* Block general dunder access if allow_dunder_access=0 */
    if (check_dunder) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxAttributeError,
                     "dunder attribute access blocked in sandbox: '%U'", name);
        sandbox->suppress_checks = 0;
        return -1;
    }

    return 0;
}

/* ============ Metaclass Creation Checking ============ */

/* Check if any base is `type` or a subclass of `type` (i.e., creating a metaclass).
 * A metaclass is created when a class inherits from `type`.
 * Returns: 1 if metaclass creation, 0 if normal class, -1 on error */
static int
is_metaclass_creation(PyObject *bases)
{
    if (!PyTuple_Check(bases)) {
        return 0;
    }
    Py_ssize_t n = PyTuple_GET_SIZE(bases);
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *base = PyTuple_GET_ITEM(bases, i);
        /* Check if base is `type` itself */
        if (base == (PyObject *)&PyType_Type) {
            return 1;
        }
        /* Check if base is a metaclass (subclass of type).
         * We use PyType_IsSubtype to check if the base IS a type object
         * and then check if it's a subtype of type.
         * All metaclasses are instances of type, but we specifically want
         * classes whose instances are classes (i.e., metaclasses). */
        if (PyType_Check(base)) {
            /* Check if this type is a subclass of type (a metaclass) */
            int is_subtype = PyObject_IsSubclass(base, (PyObject *)&PyType_Type);
            if (is_subtype < 0) {
                return -1;  /* Error */
            }
            if (is_subtype) {
                return 1;
            }
        }
    }
    return 0;
}

/* _PySandbox_CheckMetaclassAllowed - Check if metaclass creation/usage is allowed
 *
 * Called from __build_class__ to prevent sandbox code from:
 * 1. Creating metaclasses (subclassing type)
 * 2. Using metaclasses that were created in sandbox (future enhancement)
 *
 * When allow_class_creation=1:
 * - Sandbox code can create normal classes (inheriting from object, etc.)
 * - Sandbox code CANNOT create metaclasses (inheriting from type)
 * - Sandbox code CAN use trusted metaclasses passed from outside sandbox
 *
 * Returns: 0 if allowed, -1 if blocked (SandboxSecurityError set)
 */
int
_PySandbox_CheckMetaclassAllowed(PyObject *meta, PyObject *bases)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }
    _PySandboxConfig *config = &sandbox->config;

    /* If class creation is disabled, don't do special metaclass checks here.
     * The dunder access checks will block class creation anyway. */
    if (!config->allow_class_creation) {
        return 0;
    }

    if (sandbox->registered_filenames == NULL) {
        return 0;  /* No scope registered */
    }

    /* Check if currently in sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL) {
        return 0;
    }
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;  /* Error during scope check */
    }
    if (!in_scope) {
        return 0;  /* Not in scope, allow everything */
    }

    /* Check 1: Block metaclass CREATION (subclassing type).
     * This prevents sandbox code from creating their own metaclasses. */
    int creating_metaclass = is_metaclass_creation(bases);
    if (creating_metaclass < 0) {
        return -1;  /* Error */
    }
    if (creating_metaclass) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxSecurityError,
                        "creating metaclasses (subclassing type) is not allowed in sandbox");
        sandbox->suppress_checks = 0;
        return -1;
    }

    /* Note: We explicitly ALLOW using non-standard metaclasses here.
     * If meta != type, it means the class has a custom metaclass.
     * This is ALLOWED because:
     * - The metaclass must come from trusted code (sandbox can't create metaclasses
     *   due to Check 1 above)
     * - This allows sandboxed code to subclass from base classes that have
     *   metaclasses (like ABCMeta, dataclasses, etc.) */

    return 0;  /* Allowed */
}

/* ============ Unsafe Operation Checking ============ */

/* _PySandbox_CheckUnsafeBlocked - Check if an unsafe operation is blocked
 *
 * This function blocks dangerous operations (compile(), gc introspection, etc.)
 * in sandbox scope unless allow_unsafe=1. It is used to prevent escape vectors.
 *
 * Returns: 0 if allowed, -1 if blocked (SandboxSecurityError set)
 */
int
_PySandbox_CheckUnsafeBlocked(const char *operation)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }
    if (sandbox->config.allow_unsafe) {
        return 0;  /* Unsafe operations allowed */
    }
    if (sandbox->registered_filenames == NULL) {
        return 0;  /* No scope registered */
    }

    /* Check if currently in sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;  /* Error during scope check */
    }
    if (!in_scope) {
        return 0;  /* Not in scope */
    }

    /* Block the unsafe operation */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxSecurityError,
                 "%s is not allowed in sandbox scope", operation);
    sandbox->suppress_checks = 0;
    return -1;
}

/* ============ I/O Operation Checking ============ */

/* _PySandbox_CheckIOAllowed - Check if I/O operations are blocked
 *
 * This function blocks I/O operations (file open, socket, raw fd)
 * in sandbox scope unless allow_io=1. It is used to prevent data exfiltration.
 *
 * Returns: 0 if allowed, -1 if blocked (SandboxSecurityError set)
 */
int
_PySandbox_CheckIOAllowed(const char *operation)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }
    if (sandbox->config.allow_io) {
        return 0;  /* I/O operations allowed */
    }
    if (sandbox->registered_filenames == NULL) {
        return 0;  /* No scope registered */
    }

    /* Check if currently in sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;  /* Error during scope check */
    }
    if (!in_scope) {
        return 0;  /* Not in scope */
    }

    /* Block the I/O operation */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxSecurityError,
                 "%s is not allowed in sandbox scope (I/O blocked)", operation);
    sandbox->suppress_checks = 0;
    return -1;
}

/* ============ Module Access Checking ============ */

/* _PySandbox_CheckModuleAccess - Check if accessing a module is allowed
 *
 * When module_access_restrict_mode is enabled, this function checks if a module
 * is in the allowed_modules set. It is called from module_getattro() before
 * allowing any attribute access on the module.
 *
 * This provides defense in depth: even if an attacker obtains a reference
 * to a dangerous module (e.g., via sys.modules before sandbox activation),
 * they cannot use it within sandbox scope unless it's in the allowlist.
 *
 * Returns: 0 if allowed, -1 if blocked (SandboxSecurityError set)
 */
int
_PySandbox_CheckModuleAccess(PyObject *module)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }

    /* Fast exit if module access restriction is not enabled */
    if (!sandbox->config.module_access_restrict_mode) {
        return 0;
    }

    if (sandbox->registered_filenames == NULL) {
        return 0;  /* No scope registered */
    }

    /* Check if currently in sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;  /* Error during scope check */
    }
    if (!in_scope) {
        return 0;  /* Not in scope */
    }

    /* Get module name */
    PyObject *mod_name = PyModule_GetNameObject(module);
    if (mod_name == NULL) {
        PyErr_Clear();
        return 0;  /* Can't determine name, allow */
    }

    /* If no allowlist is set, block everything */
    if (sandbox->allowed_modules == NULL ||
        PySet_GET_SIZE(sandbox->allowed_modules) == 0) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxSecurityError,
                     "access to module '%U' is not allowed in sandbox (no modules allowed)", mod_name);
        sandbox->suppress_checks = 0;
        Py_DECREF(mod_name);
        return -1;
    }

    /* Check if module is in allowlist */
    int allowed = PySet_Contains(sandbox->allowed_modules, mod_name);
    if (allowed < 0) {
        Py_DECREF(mod_name);
        return -1;  /* Error during set lookup */
    }

    /* Also check base module name for submodules (e.g., "xml" for "xml.etree.ElementTree")
     * Only if allow_submodules is enabled (default). */
    if (!allowed && sandbox->config.allow_submodules) {
        const char *name_str = PyUnicode_AsUTF8(mod_name);
        if (name_str) {
            const char *dot = strchr(name_str, '.');
            if (dot) {
                PyObject *base = PyUnicode_FromStringAndSize(name_str, dot - name_str);
                if (base) {
                    allowed = PySet_Contains(sandbox->allowed_modules, base);
                    Py_DECREF(base);
                    if (allowed < 0) {
                        Py_DECREF(mod_name);
                        return -1;  /* Error during set lookup */
                    }
                }
            }
        }
    }

    if (!allowed) {
        sandbox->suppress_checks = 1;
        PyErr_Format(PyExc_SandboxSecurityError,
                     "access to module '%U' is not allowed in sandbox", mod_name);
        sandbox->suppress_checks = 0;
        Py_DECREF(mod_name);
        return -1;
    }

    Py_DECREF(mod_name);
    return 0;
}

/* ============ Public C API ============ */

int
PySandbox_SetConfig(
    Py_ssize_t max_int_digits,
    Py_ssize_t max_str_length,
    Py_ssize_t max_bytes_length,
    Py_ssize_t max_list_size,
    Py_ssize_t max_dict_size,
    Py_ssize_t max_set_size,
    int allow_float)
{
    /* Block from within sandbox scope. */
    if (_PySandbox_CheckConfigModification() < 0) {
        return -1;
    }

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
    _PySandboxConfig *config = &sandbox->config;
    config->max_int_digits = max_int_digits;
    config->max_str_length = max_str_length;
    config->max_bytes_length = max_bytes_length;
    config->max_list_size = max_list_size;
    config->max_dict_size = max_dict_size;
    config->max_set_size = max_set_size;
    config->allow_float = allow_float;

    return 0;
}

void
PySandbox_GetConfig(
    Py_ssize_t *max_int_digits,
    Py_ssize_t *max_str_length,
    Py_ssize_t *max_bytes_length,
    Py_ssize_t *max_list_size,
    Py_ssize_t *max_dict_size,
    Py_ssize_t *max_set_size,
    int *allow_float)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    _PySandboxConfig *config = (interp != NULL) ? &interp->sandbox.config : NULL;

    if (max_int_digits) *max_int_digits = config ? config->max_int_digits : 0;
    if (max_str_length) *max_str_length = config ? config->max_str_length : 0;
    if (max_bytes_length) *max_bytes_length = config ? config->max_bytes_length : 0;
    if (max_list_size) *max_list_size = config ? config->max_list_size : 0;
    if (max_dict_size) *max_dict_size = config ? config->max_dict_size : 0;
    if (max_set_size) *max_set_size = config ? config->max_set_size : 0;
    if (allow_float) *allow_float = config ? config->allow_float : 1;
}

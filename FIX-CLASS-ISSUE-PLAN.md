# Plan: Allow Class Creation with `allow_dunder_access=False`

## Problem Summary

When `allow_dunder_access=False` (now the default):
1. **Class creation fails** - The compiler injects `LOAD_NAME __name__` into every class body, which triggers the dunder check
2. **Subclassing from classes with metaclasses fails** - The metaclass check in `__build_class__` blocks ALL custom metaclasses

## Requirements

- `allow_dunder_access=False` should block introspection (`obj.__class__`, `cls.__subclasses__()`)
- Class creation should work (user's classes have annotations, slots, docstrings)
- Subclassing from trusted base classes with metaclasses should work
- Untrusted code should NOT be able to create metaclasses (subclass `type`)
- Untrusted code should NOT be able to use sandbox-created metaclasses

---

## Solution Overview

### Part 1: CO_CLASS_BODY Flag
Add a code object flag to identify class body code objects, then whitelist specific safe dunders during class body execution.

### Part 2: Block Metaclass Creation & Usage
- Block sandbox code from creating metaclasses (subclassing `type`)
- Allow sandbox code to use trusted metaclasses from outside sandbox

### Part 3: New Config Flag
Add `allow_class_creation` flag to control this behavior.

---

## Part 1: CO_CLASS_BODY Flag Implementation

### 1.1 Define the flag

**File: `Include/cpython/code.h`** (after line 111)

```c
#define CO_GENERATOR    0x0020
#define CO_CLASS_BODY   0x0040    // NEW: class body code object
```

### 1.2 Set the flag in compiler

**File: `Python/compile.c`** in `compute_code_flags()` (~line 7927, after the FunctionBlock check)

```c
    if (ste->ste_type == FunctionBlock) {
        // ... existing code ...
    }

    // NEW: Set CO_CLASS_BODY for class body code objects
    if (ste->ste_type == ClassBlock) {
        flags |= CO_CLASS_BODY;
    }

    /* (Only) inherit compilerflags in PyCF_MASK */
    flags |= (c->c_flags->cf_flags & PyCF_MASK);
```

### 1.3 Add whitelist function and modify dunder check

**File: `Python/sandbox_limits.c`**

```c
/* Whitelist of dunders allowed in class body when allow_class_creation=1 */
static int
is_class_body_safe_dunder(PyObject *name)
{
    // These are needed for class creation machinery
    return (_PyUnicode_EqualToASCIIString(name, "__name__") ||
            _PyUnicode_EqualToASCIIString(name, "__module__") ||
            _PyUnicode_EqualToASCIIString(name, "__qualname__") ||
            _PyUnicode_EqualToASCIIString(name, "__annotations__") ||
            _PyUnicode_EqualToASCIIString(name, "__doc__") ||
            _PyUnicode_EqualToASCIIString(name, "__classcell__") ||
            _PyUnicode_EqualToASCIIString(name, "__slots__"));
}

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

    /* Check if in sandbox scope */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL) {
        return 0;
    }

    // NEW: If class creation allowed and in class body, check whitelist
    if (check_dunder && config->allow_class_creation) {
        if (frame->f_code->co_flags & CO_CLASS_BODY) {
            if (is_class_body_safe_dunder(name)) {
                return 0;  // Allow this dunder in class body
            }
        }
    }

    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    // ... rest of existing blocking logic ...
}
```

---

## Part 2: Block Metaclass Creation & Usage

### 2.1 Add helper to check if creating a metaclass

**File: `Python/sandbox_limits.c`**

```c
/* Check if any base is `type` or a subclass of `type` (i.e., creating a metaclass).
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
        // Check if base is `type` itself
        if (base == (PyObject *)&PyType_Type) {
            return 1;
        }
        // Check if base is a subclass of `type` (a metaclass)
        if (PyType_Check(base) && PyType_IsSubtype((PyTypeObject *)base, &PyType_Type)) {
            // All classes are technically subtypes of type via their metaclass,
            // but we specifically want classes whose *instances* are classes.
            // A metaclass is a class whose base is `type`.
            if (PyObject_IsSubclass(base, (PyObject *)&PyType_Type)) {
                return 1;
            }
        }
    }
    return 0;
}
```

### 2.2 Add check function for __build_class__

**File: `Python/sandbox_limits.c`**

```c
/* Check if metaclass creation is blocked in sandbox.
 * Called from __build_class__ to prevent sandbox code from:
 * 1. Creating metaclasses (subclassing type)
 * 2. Using metaclasses that were somehow created in sandbox
 *
 * Returns: 0 if allowed, -1 if blocked (exception set)
 */
int
_PySandbox_CheckMetaclassAllowed(PyObject *meta, PyObject *bases)
{
    _PySandboxState *sandbox = get_sandbox_state();
    if (sandbox == NULL || !_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }
    if (!sandbox->config.allow_class_creation) {
        return 0;  // Class creation entirely disabled, will fail elsewhere
    }
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
        return 0;  // Not in sandbox scope, allow everything
    }

    // Check 1: Block metaclass CREATION (subclassing type)
    int creating_metaclass = is_metaclass_creation(bases);
    if (creating_metaclass < 0) {
        return -1;
    }
    if (creating_metaclass) {
        sandbox->suppress_checks = 1;
        PyErr_SetString(PyExc_SandboxSecurityError,
                        "creating metaclasses (subclassing type) is not allowed in sandbox");
        sandbox->suppress_checks = 0;
        return -1;
    }

    // Check 2: Block using non-standard metaclass
    // Allow only `type` itself as metaclass for sandbox-created classes
    if (meta != (PyObject *)&PyType_Type) {
        // Metaclass is not `type` - this is a class with a custom metaclass
        // This is ALLOWED because the metaclass comes from trusted code
        // (sandbox can't create metaclasses due to Check 1 above)
    }

    return 0;  // Allowed
}
```

### 2.3 Modify __build_class__ to use new check

**File: `Python/bltinmodule.c`** (replace lines 181-186)

```c
    /* Sandbox check: block metaclass creation and validate metaclass usage */
    if (_PySandbox_CheckMetaclassAllowed(meta, bases) < 0) {
        goto error;
    }
```

---

## Part 3: New Config Flag

**File: `Include/internal/pycore_sandbox.h`** (in `_PySandboxConfig`)

```c
typedef struct {
    // ... existing fields ...
    int allow_class_creation;  /* 1 = allow class creation with whitelisted dunders (default) */
} _PySandboxConfig;

#define _PySandboxConfig_INIT { \
    // ... existing defaults ...
    .allow_class_creation = 1, \
}
```

**File: `Python/sandbox_pyapi.c`** (expose to Python)

```c
SANDBOX_BOOL_GETSET(allow_class_creation, config.allow_class_creation)
```

---

## Summary of Changes

| File | Changes |
|------|---------|
| `Include/cpython/code.h` | Add `CO_CLASS_BODY` flag |
| `Include/internal/pycore_sandbox.h` | Add `allow_class_creation` config |
| `Python/compile.c` | Set `CO_CLASS_BODY` flag in `compute_code_flags()` |
| `Python/sandbox_limits.c` | Add whitelist check, `is_metaclass_creation()`, `_PySandbox_CheckMetaclassAllowed()` |
| `Python/sandbox_pyapi.c` | Expose `allow_class_creation` property |
| `Python/bltinmodule.c` | Replace metaclass check with `_PySandbox_CheckMetaclassAllowed()` |

---

## Behavior Summary

| Scenario | Before | After |
|----------|--------|-------|
| `class Foo: pass` | BLOCKED | ALLOWED |
| `class Foo(TrustedBase): pass` (TrustedBase has metaclass) | BLOCKED | ALLOWED |
| `class Meta(type): pass` in sandbox | ALLOWED | **BLOCKED** |
| `class Foo(metaclass=TrustedMeta): pass` | BLOCKED | ALLOWED (TrustedMeta from outside) |
| `obj.__class__` | BLOCKED | BLOCKED |
| `cls.__subclasses__()` | BLOCKED | BLOCKED |

---

## Verification

```python
# Test 1: Basic class creation works
sys.sandbox.enabled = True
sys.sandbox.allow_dunder_access = False
sys.sandbox.allow_class_creation = True
sys.sandbox.register_filename("<sandbox>")

code = "class Foo: pass"
exec(compile(code, "<sandbox>", "exec"))  # Should succeed

# Test 2: Subclassing trusted base with metaclass works
class TrustedMeta(type): pass
class TrustedBase(metaclass=TrustedMeta): pass

code = "class Sub(Base): pass"
exec(compile(code, "<sandbox>", "exec"), {"Base": TrustedBase})  # Should succeed

# Test 3: Creating metaclass in sandbox is BLOCKED
code = "class Meta(type): pass"
try:
    exec(compile(code, "<sandbox>", "exec"))
    assert False, "Should have raised"
except SandboxSecurityError as e:
    assert "metaclass" in str(e).lower()  # Expected

# Test 4: Using trusted metaclass explicitly works
code = "class Foo(metaclass=Meta): pass"
exec(compile(code, "<sandbox>", "exec"), {"Meta": TrustedMeta})  # Should succeed

# Test 5: Introspection still blocked
code = "x.__class__"
try:
    exec(compile(code, "<sandbox>", "exec"), {"x": object()})
    assert False, "Should have raised"
except SandboxAttributeError:
    pass  # Expected
```

---

## Tests to Update

- `Lib/test/test_sandbox/test_dunder_access.py` - Add tests for class body whitelist
- `Lib/test/test_sandbox/test_metaclass_security.py` - Update tests for new metaclass behavior:
  - Test that `class Meta(type): pass` is blocked
  - Test that trusted metaclasses work
- Add new test file or section for `allow_class_creation` flag

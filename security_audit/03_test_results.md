# Security Test Results

**Date:** 2026-01-29
**Audit Phase:** 5 - Test Implementation and Execution

---

## Summary

| Category | Tested | Bypasses Confirmed | Blocked | Severity |
|----------|--------|-------------------|---------|----------|
| Container Copy/Update | 4 | **3** | 1 | CRITICAL |
| Container Incremental | 4 | 0 | **4** | SECURED |
| Type Literals | 3 | **3** | 0 | HIGH |
| Compile-Time Folding | 4 | **2** | 2 | HIGH |
| Dunder Access | 3 | **2** | 1 | HIGH |
| Import/Scope | 4 | **3** | 1 | CRITICAL |
| File System Access | 1 | 0 | **1** | SECURED |
| Process Control | 1 | **1** | 0 | HIGH |
| DoS Vectors | 1 | **1** | 0 | MEDIUM |
| **TOTAL** | **25** | **15** | **10** | - |

---

## Detailed Results

### CRITICAL: Container Copy/Update Bypasses

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| Dict copy | HYP-002 | **BYPASS** | Copied 500-item dict with max_dict_size=100 |
| Set copy | HYP-004 | **BYPASS** | Copied 500-item set with max_set_size=100 |
| dict.update() | HYP-020 | **BYPASS** | update() created 500 items with max_dict_size=100 |
| Dict incremental | HYP-001 | BLOCKED | "Dict size (101) exceeds sandbox limit (100)" |
| Set incremental | HYP-003 | BLOCKED | "Set size (101) exceeds sandbox limit (100)" |
| dict() constructor | HYP-005 | BLOCKED | "Dict size (101) exceeds sandbox limit (100)" |
| set() constructor | HYP-006 | BLOCKED | "Set size (101) exceeds sandbox limit (100)" |

**Key Finding:** Copy and update operations bypass size limits; individual insertions are properly checked.

---

### HIGH: Type Literal Bypasses

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| Float literal | HYP-007 | **BYPASS** | `1.5` created despite allow_float=0 |
| Complex literal | HYP-008 | **BYPASS** | `1+2j` created despite allow_complex=0 |
| Division float | HYP-019 | **BYPASS** | `1/2` created float despite allow_float=0 |
| Tuple multiply | HYP-011 | BLOCKED | "Tuple size (300) exceeds sandbox limit (50)" |

**Key Finding:** Type restrictions only apply to constructor calls, not literals or arithmetic.

---

### HIGH: Compile-Time Folding Bypasses

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| String literal mult | HYP-009 | **BYPASS** | `"a" * 200` created despite max_str_length=100 |
| String runtime mult | HYP-009b | BLOCKED | "String length (200) exceeds sandbox limit (100)" |
| Bytes literal mult | HYP-010 | **BYPASS** | `b"a" * 200` created despite max_bytes_length=100 |
| Bytes runtime mult | HYP-010b | BLOCKED | "Bytes length (200) exceeds sandbox limit (100)" |

**Key Finding:** Compile-time constant folding (up to 4096 chars) bypasses runtime size checks.

---

### HIGH: Dunder Access Bypasses

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| __builtins__ LOAD_NAME | HYP-012 | **BYPASS** | Accessible via name, not attribute |
| __builtins__ via globals() | HYP-013 | **BYPASS** | Accessible via dict key lookup |
| __import__ from builtins | HYP-012b | BLOCKED | "dunder attribute access blocked" |

**Key Finding:** `__builtins__` is accessible, but `__import__` within it is blocked by dunder checks.

---

### CRITICAL: Import/Scope Bypasses

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| Unregistered filename | HYP-014 | **BYPASS** | Code with external filename bypassed statement limit |
| sys.modules access | HYP-015 | **BYPASS** | Accessed os via sys.modules, cwd=/home/msbrogli/Hathor/cpython |
| Module init scope | HYP-018 | **BYPASS** | Imported json despite max_statements=5 |
| Generator frame | HYP-016 | BLOCKED | "Sandbox iteration limit exceeded" |

**Key Finding:** Scope detection has critical gaps for pre-compiled code and imported module execution.

---

### SECURED: File System Access

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| open() file access | HYP-026 | BLOCKED | "open() is not allowed in sandbox scope (I/O blocked)" |

**Key Finding:** `open()` is now blocked when sandbox is active with `import_restrict_mode=1`. For defense in depth, consider removing from `__builtins__` anyway.

---

### HIGH: Process Control Bypass

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| sys.exit() | HYP-027 | **BYPASS** | sys.exit() raised SystemExit |

**Key Finding:** If `sys` module is allowed, `sys.exit()` raises `SystemExit` which can crash harness.

---

### MEDIUM: DoS Vectors

| Test | Hypothesis | Result | Details |
|------|------------|--------|---------|
| input() DoS | HYP-028 | **BYPASS** | input() is accessible (blocks indefinitely if called) |

**Key Finding:** `input()` can block forever waiting for stdin. Remove from `__builtins__`.

---

### SECURED: Properly Blocked

| Test | Result | Protection Mechanism |
|------|--------|---------------------|
| Dict incremental growth (HYP-001) | BLOCKED | `_PySandbox_CheckDictSize` in insertdict |
| Set incremental growth (HYP-003) | BLOCKED | `_PySandbox_CheckSetSize` in set_add_entry |
| dict() constructor (HYP-005) | BLOCKED | Size check during iteration |
| set() constructor (HYP-006) | BLOCKED | Size check during iteration |
| String runtime mult (HYP-009b) | BLOCKED | `_PySandbox_CheckStrLength` |
| Bytes runtime mult (HYP-010b) | BLOCKED | `_PySandbox_CheckBytesLength` |
| Tuple multiplication (HYP-011) | BLOCKED | `_PySandbox_CheckTupleSize` |
| __import__ access (HYP-012b) | BLOCKED | Dunder attribute check |
| Generator iteration (HYP-016) | BLOCKED | Iterator wrapper |
| List multiplication (sanity) | BLOCKED | `_PySandbox_CheckListSize` |

---

## Confirmed Bypass Vectors

### 1. Container Copy Bypass (CRITICAL)
```python
big_dict = {i: i for i in range(500)}  # Outside scope
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
my_dict = big_dict.copy()  # BYPASSES - 500 items created
```

### 2. dict.update() Bypass (CRITICAL)
```python
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
my_dict = {}
my_dict.update(big_dict)  # BYPASSES - 500 items created
```

### 3. Type Literal Bypass (HIGH)
```python
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<test>')
x = 1.5  # BYPASSES - Float literal created
y = 1 / 2  # BYPASSES - Float from division
```

### 4. Compile-Time Folding Bypass (HIGH)
```python
sys.sandbox.max_str_length = 100
sys.sandbox.add_filename('<test>')
s = "a" * 200  # BYPASSES - Folded at compile time
```

### 5. Unregistered Filename Bypass (CRITICAL)
```python
code = compile('malicious()', '<EXTERNAL>', 'exec')  # Different filename
sys.sandbox.add_filename('<SANDBOX>')  # Only sandbox registered
exec(code)  # BYPASSES - Frame not in scope, all limits skipped
```

### 6. sys.modules Access Bypass (CRITICAL)
```python
import os  # Pre-imported
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<test>')
os_mod = sys.modules.get('os')  # BYPASSES import check
os_mod.system('id')  # Direct access to dangerous module
```

### 7. Module Init Scope Bypass (HIGH)
```python
sys.sandbox.max_statements = 5
sys.sandbox.allowed_imports = frozenset([('json', '')])
sys.sandbox.add_filename('<test>')
import json  # BYPASSES - json init runs many statements outside scope
```

### 8. open() File Access (NOW BLOCKED)
```python
sys.sandbox.add_filename('<test>')
data = open('/etc/passwd').readline()  # BLOCKED - "open() is not allowed in sandbox scope"
```

### 9. sys.exit() SystemExit Bypass (HIGH)
```python
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<test>')
import sys
sys.exit(1)  # BYPASSES - raises SystemExit, crashes harness
```

### 10. input() DoS (MEDIUM)
```python
sys.sandbox.add_filename('<test>')
input()  # BYPASSES - blocks indefinitely waiting for stdin
```

---

## Corrections to Initial Analysis

### Previously Thought VULNERABLE, Actually BLOCKED:
1. **Dict incremental growth (HYP-001)**: The insertion check at each step IS working - the resize path doesn't need a separate check because size is tracked by `ma_used`.
2. **Set incremental growth (HYP-003)**: Same - size check works correctly.
3. **Tuple multiplication (HYP-011)**: This was listed as VULNERABLE in the security analysis but tests show it IS blocked.

### Previously Uncertain, Now Confirmed:
1. **Arithmetic float creation (HYP-019)**: CONFIRMED bypass - `1/2` creates float even with allow_float=0.

---

## Risk Assessment

| Vector | Severity | Impact | Likelihood | Mitigation Available |
|--------|----------|--------|------------|---------------------|
| Container copy/update | CRITICAL | Memory exhaustion | HIGH | Add checks to copy/update |
| Unregistered filename | CRITICAL | All limits bypassed | HIGH | Harness must register filenames |
| sys.modules access | CRITICAL | Code execution | HIGH | Don't allow sys, or clear sys.modules |
| Module init scope | HIGH | Statement limit bypass | MEDIUM | Module init runs outside scope |
| Type literals | HIGH | Type policy bypass | HIGH | Accept or block at compile time |
| Compile-time folding | HIGH | Size limit bypass | MEDIUM | Limit AST optimizer or check consts |
| __builtins__ access | HIGH | Access to builtins | HIGH | Provide restricted builtins dict |
| **sys.exit()** | HIGH | Process termination | HIGH | Catch SystemExit in harness |
| **input() DoS** | MEDIUM | Denial of service | MEDIUM | Remove from __builtins__ |

---

## Recommendations

### Immediate Fixes Required

1. **Add sandbox check to `PyDict_Copy()`** - `Objects/dictobject.c:3025`
2. **Add sandbox check to `set_copy()`** - `Objects/setobject.c:1103`
3. **Add sandbox check to `dict_merge()`** - `Objects/dictobject.c:2828`

### Harness-Level Mitigations

4. **Always compile code with registered filenames** - Use `compile(source, '<registered_filename>', 'exec')`
5. **Provide restricted `__builtins__` dict** - Remove `__import__`, `open`, `input`, `eval`, `exec`, `compile`
6. **Don't allow `sys` module** - Or clear dangerous modules from `sys.modules`
7. **Catch SystemExit** - In execution harness
8. **Remove open() from builtins** - Prevents file system access
9. **Remove input() from builtins** - Prevents DoS via stdin blocking

### Accept or Document

8. **Type literals bypass** - Document that `allow_float=0` doesn't block `1.5` literals
9. **Compile-time folding** - Document AST optimizer limit of 4096 chars
10. **Module init outside scope** - Expected behavior; module code has own filename

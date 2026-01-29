# Bypass Hypotheses - Security Audit

**Date:** 2026-01-29
**Audit Phase:** 4 - Bypass Hypothesis Generation

---

## Summary Statistics

| Priority | Count | Status |
|----------|-------|--------|
| CRITICAL | 6 | High-confidence bypasses |
| HIGH | 9 | Likely exploitable |
| MEDIUM | 7 | Needs testing |
| LOW | 5 | Unlikely but worth testing |
| SECURED | 1 | open() now blocked |

---

## CRITICAL: Container Resize/Copy Bypasses

### HYP-001: Dict Incremental Growth Triggers Unchecked Resize
**Target validation:** VAL-DICT-002
**Attack mechanism:** `dictresize()` at `Objects/dictobject.c:1417` has NO sandbox check. Incremental insertions each pass the `ma_used + 1` check, but when load factor exceeds threshold, resize doubles capacity unchecked.

**Test flow:**
```python
import sys
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
d = {}
for i in range(500):
    d[i] = i  # Each passes check, resize bypasses
assert len(d) == 500  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Confirmed missing validation. Resize path completely unchecked.

---

### HYP-002: Dict Copy from External Large Dict
**Target validation:** VAL-DICT-003
**Attack mechanism:** `PyDict_Copy()` at `Objects/dictobject.c:3025` has NO sandbox check.

**Test flow:**
```python
import sys
big_dict = {i: i for i in range(500)}  # Outside sandbox
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
my_dict = big_dict.copy()  # NO CHECK
assert len(my_dict) == 500  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Confirmed missing validation.

---

### HYP-003: Set Incremental Growth Triggers Unchecked Resize
**Target validation:** VAL-SET-002
**Attack mechanism:** `set_table_resize()` at `Objects/setobject.c:241` has NO sandbox check.

**Test flow:**
```python
import sys
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<test>')
s = set()
for i in range(500):
    s.add(i)  # Each passes check, resize bypasses
assert len(s) == 500  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Confirmed missing validation.

---

### HYP-004: Set Copy from External Large Set
**Target validation:** VAL-SET-003
**Attack mechanism:** `set_copy()` at `Objects/setobject.c:1103` has NO sandbox check.

**Test flow:**
```python
import sys
big_set = {i for i in range(500)}  # Outside sandbox
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<test>')
my_set = big_set.copy()  # NO CHECK
assert len(my_set) == 500  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Confirmed missing validation.

---

### HYP-005: dict() Constructor with Large Iterable
**Target validation:** VAL-DICT-002
**Attack mechanism:** `dict()` constructor iterates and inserts, triggering unchecked resize.

**Test flow:**
```python
import sys
big_items = [(i, i) for i in range(500)]  # Outside sandbox
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
my_dict = dict(big_items)  # Resize unchecked
assert len(my_dict) == 500  # BYPASS
```

**Confidence:** HIGH

---

### HYP-006: set() Constructor with Large Iterable
**Target validation:** VAL-SET-002
**Attack mechanism:** `set()` constructor calls `set_update_internal()` which resizes without check.

**Test flow:**
```python
import sys
big_list = list(range(500))  # Outside sandbox
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<test>')
my_set = set(big_list)  # Resize unchecked
assert len(my_set) == 500  # BYPASS
```

**Confidence:** HIGH

---

## HIGH: Type and Literal Bypasses

### HYP-007: Float Literal Bypasses Type Check
**Target validation:** VAL-TYPE-001
**Attack mechanism:** Float literals loaded via LOAD_CONST are created at compile time, not runtime.

**Test flow:**
```python
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<test>')
code = compile('x = 1.5', '<test>', 'exec')
exec(code)  # Literal in co_consts bypasses check
assert isinstance(x, float)  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Type check only runs on `float()` constructor, not LOAD_CONST.

---

### HYP-008: Complex Literal Bypasses Type Check
**Target validation:** VAL-TYPE-001
**Attack mechanism:** Complex literals `1+2j` also bypass runtime type checks.

**Test flow:**
```python
import sys
sys.sandbox.allow_complex = 0
sys.sandbox.add_filename('<test>')
code = compile('x = 1+2j', '<test>', 'exec')
exec(code)  # Literal bypasses check
assert isinstance(x, complex)  # BYPASS
```

**Confidence:** HIGH

---

### HYP-009: String Multiplication Compile-Time Folding
**Target validation:** VAL-STR-001
**Attack mechanism:** AST optimizer folds `'a' * N` for N up to 4096/len(s). If sandbox limit < 4096, bypass possible.

**Test flow:**
```python
import sys
sys.sandbox.max_str_length = 100
# Compiled outside sandbox scope:
code = compile('s = "a" * 200', '<test>', 'exec')
sys.sandbox.add_filename('<test>')
exec(code)
assert len(s) == 200  # BYPASS (folded at compile time)
```

**Confidence:** HIGH
**Reasoning:** AST optimizer MAX_STR_SIZE=4096 in `ast_opt.c`.

---

### HYP-010: Bytes Multiplication Compile-Time Folding
**Target validation:** VAL-BYTES-001
**Attack mechanism:** Same as string folding but for bytes.

**Test flow:**
```python
import sys
sys.sandbox.max_bytes_length = 100
code = compile('b = b"a" * 200', '<test>', 'exec')
sys.sandbox.add_filename('<test>')
exec(code)
assert len(b) == 200  # BYPASS
```

**Confidence:** HIGH

---

### HYP-011: Tuple Multiplication Bypass
**Target validation:** VAL-TUPLE-001
**Attack mechanism:** `tuplerepeat()` in `Objects/tupleobject.c` has NO size check.

**Test flow:**
```python
import sys
sys.sandbox.max_tuple_size = 50
sys.sandbox.add_filename('<test>')
t = (1, 2, 3) * 100
assert len(t) == 300  # BYPASS
```

**Confidence:** HIGH
**Reasoning:** Documented as VULNERABLE in security analysis.

---

## HIGH: Dunder and Import Bypasses

### HYP-012: __builtins__ Access via LOAD_NAME
**Target validation:** VAL-DUNDER-001
**Attack mechanism:** `__builtins__` is accessed via LOAD_NAME opcode, not LOAD_ATTR. Dunder check only applies to LOAD_ATTR.

**Test flow:**
```python
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<test>')
code = compile('b = __builtins__', '<test>', 'exec')
exec(code)  # LOAD_NAME, not LOAD_ATTR
# __builtins__ is accessible!
```

**Confidence:** HIGH
**Reasoning:** Confirmed in security analysis. Mitigation is restricted builtins dict.

---

### HYP-013: __builtins__ via globals() Dict Lookup
**Target validation:** VAL-DUNDER-001
**Attack mechanism:** `globals()['__builtins__']` uses dict access, not attribute access.

**Test flow:**
```python
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<test>')
code = compile('b = globals()["__builtins__"]', '<test>', 'exec')
exec(code)  # Dict access bypasses dunder check
```

**Confidence:** HIGH

---

### HYP-014: Pre-compiled Code with Unregistered Filename
**Target validation:** VAL-IMPORT-001, VAL-SCOPE-001
**Attack mechanism:** Code compiled with different filename escapes scope detection.

**Test flow:**
```python
import sys
# Compile with unregistered filename
code = compile('import os', '<external>', 'exec')
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset()
sys.sandbox.add_filename('<sandbox>')  # Different from code's filename
exec(code)  # Frame's co_filename='<external>' not in registered set
# Import check passes because not in scope!
```

**Confidence:** HIGH
**Reasoning:** Scope check uses `frame->f_code->co_filename`.

---

### HYP-015: sys.modules Direct Access
**Target validation:** VAL-IMPORT-001
**Attack mechanism:** Access already-loaded modules via `sys.modules` dict without triggering import check.

**Test flow:**
```python
import sys
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<test>')
code = compile('os = sys.modules.get("os")', '<test>', 'exec')
exec(code, {'sys': sys})
# If os was pre-imported, it's now accessible without import
```

**Confidence:** HIGH if sys allowed

---

## MEDIUM: Scope Escape Attempts

### HYP-016: Generator Frame Scope Escape
**Target validation:** VAL-SCOPE-001
**Attack mechanism:** Generator's frame has its definition's `co_filename`, not caller's.

**Test flow:**
```python
import sys
def gen():  # Defined outside sandbox
    yield 1
    # Operations here use gen's co_filename

sys.sandbox.max_list_size = 5
sys.sandbox.add_filename('<test>')
code = compile('result = list(gen())', '<test>', 'exec')
exec(code, {'gen': gen})
# Generator frame's filename not registered - escapes scope
```

**Confidence:** MEDIUM
**Reasoning:** Needs testing. Generator execution may switch frames.

---

### HYP-017: Callback from C Extension
**Target validation:** VAL-SCOPE-001
**Attack mechanism:** Callback defined outside sandbox executes with its original filename.

**Test flow:**
```python
import sys
def callback():  # Defined outside
    return [1] * 1000  # Exceeds limit but callback filename not registered

sys.sandbox.max_list_size = 10
sys.sandbox.add_filename('<test>')
# If functools.reduce or similar allowed:
code = compile('functools.reduce(lambda a,b: callback(), [1,2], None)', '<test>', 'exec')
# callback() runs with its own filename
```

**Confidence:** MEDIUM

---

### HYP-018: Import Side Effect Scope Escape
**Target validation:** VAL-SCOPE-001
**Attack mechanism:** Module's `__init__.py` executes with module's filename, not importer's.

**Test flow:**
```python
import sys
sys.sandbox.max_statements = 10
sys.sandbox.allowed_imports = frozenset([('json', '')])  # Large module
sys.sandbox.add_filename('<test>')
code = compile('import json', '<test>', 'exec')
exec(code)
# json/__init__.py executes many statements with its own filename
# Escapes statement limit because json's filename not registered
```

**Confidence:** MEDIUM

---

### HYP-019: Arithmetic Creating Float (1/2)
**Target validation:** VAL-TYPE-001
**Attack mechanism:** Division returns float even with `allow_float=0`.

**Test flow:**
```python
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<test>')
code = compile('x = 1 / 2', '<test>', 'exec')
exec(code)
assert isinstance(x, float)  # Is this blocked?
```

**Confidence:** MEDIUM
**Reasoning:** Needs testing. Division may or may not trigger type check.

---

### HYP-020: dict.update() with Large External Dict
**Target validation:** VAL-DICT-002
**Attack mechanism:** Same as constructor but explicit update call.

**Test flow:**
```python
import sys
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<test>')
my_dict = {}
my_dict.update(big_dict)
assert len(my_dict) == 500  # BYPASS via unchecked resize
```

**Confidence:** HIGH

---

## LOW: Unlikely but Test-Worthy

### HYP-021: vars() to Access __dict__
**Target validation:** VAL-DUNDER-001
**Attack mechanism:** `vars(obj)` returns `obj.__dict__`.

**Test flow:**
```python
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<test>')
class C: pass
o = C()
code = compile('d = vars(o)', '<test>', 'exec')
exec(code, {'o': o})
# vars() implemented in C - may bypass dunder check
```

**Confidence:** LOW
**Reasoning:** vars() likely uses attribute access internally.

---

### HYP-022: type() Then Dunder Access on Type
**Target validation:** VAL-DUNDER-001
**Attack mechanism:** Get type, then access type's `__bases__`, `__mro__`.

**Test flow:**
```python
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<test>')
code = compile('t = type([]); bases = t.__bases__', '<test>', 'exec')
exec(code)
# __bases__ is dunder - should be blocked
```

**Confidence:** LOW
**Reasoning:** Dunder check applies to all objects including types.

---

### HYP-023: Exception Handler Frame Escape
**Target validation:** VAL-SCOPE-001
**Attack mechanism:** Exception handling might use different frame.

**Test flow:**
```python
import sys
sys.sandbox.add_filename('<test>')
code = compile('''
try:
    raise ValueError()
except:
    # Check if this frame is still in scope
    big_list = [1] * 1000
''', '<test>', 'exec')
exec(code)
```

**Confidence:** LOW
**Reasoning:** Exception handlers use same code object, same filename.

---

### HYP-024: String Slicing Large External String
**Target validation:** VAL-STR-001
**Attack mechanism:** Slicing may create new string without size check.

**Test flow:**
```python
import sys
big_str = 'a' * 500
sys.sandbox.max_str_length = 100
sys.sandbox.add_filename('<test>')
code = compile('s = big_str[:]', '<test>', 'exec')
exec(code, {'big_str': big_str})
# Does slice create new string? Does it check size?
```

**Confidence:** LOW
**Reasoning:** String slicing might return same object (optimization).

---

### HYP-025: Code Object co_filename Modification
**Target validation:** VAL-SCOPE-001
**Attack mechanism:** Try to modify code object's filename to escape scope.

**Test flow:**
```python
code = compile('x = 1', '<sandbox>', 'exec')
try:
    code.co_filename = '<external>'  # Try to escape
except:
    pass  # Expected: AttributeError (readonly)
```

**Confidence:** LOW
**Reasoning:** Code objects are immutable in Python 3.11.

---

## SECURED: File System Access

### HYP-026: open() File Access (NOW BLOCKED)
**Target validation:** VAL-FILE-001
**Attack mechanism:** `open()` builtin was hypothesized to provide unrestricted file system access.

**Test flow:**
```python
import sys
sys.sandbox.import_restrict_mode = 1
sys.sandbox.allowed_imports = frozenset()
sys.sandbox.add_filename('<test>')
data = open('/etc/passwd').readline()  # Now BLOCKED
```

**Result:** BLOCKED - "open() is not allowed in sandbox scope (I/O blocked)"
**Reasoning:** Sandbox now restricts I/O operations when active.

---

## HIGH: Process Control

### HYP-027: sys.exit() Causes SystemExit
**Target validation:** VAL-EXIT-001
**Attack mechanism:** If `sys` module is allowed, `sys.exit()` raises `SystemExit` which crashes the harness if not caught.

**Test flow:**
```python
import sys
sys.sandbox.allowed_imports = frozenset([('sys', '')])
sys.sandbox.add_filename('<test>')
import sys
sys.exit(1)  # Raises SystemExit
```

**Confidence:** HIGH
**Reasoning:** SystemExit is not caught by sandbox - must be handled by harness.

---

## MEDIUM: DoS Vectors

### HYP-028: input() Blocks Indefinitely (DoS)
**Target validation:** VAL-INPUT-001
**Attack mechanism:** `input()` blocks indefinitely waiting for stdin, causing denial of service.

**Test flow:**
```python
import sys
sys.sandbox.add_filename('<test>')
input()  # Blocks forever waiting for stdin
```

**Confidence:** HIGH
**Reasoning:** input() has no timeout mechanism. Must be removed from builtins.

---

## Priority Testing Order

### Phase 1: Critical Bypasses (HYP-001 to HYP-006)
Container resize/copy operations - MUST FIX

### Phase 2: High Confidence (HYP-007 to HYP-015)
Literal/type/import bypasses - Require mitigations

### Phase 3: Medium Confidence (HYP-016 to HYP-020)
Scope escapes - Need investigation

### Phase 4: Low Confidence (HYP-021 to HYP-025)
Unlikely vectors - Verify blocked

---

## Cross-Reference: Hypotheses to Validations

| Validation | Hypotheses |
|------------|------------|
| VAL-DICT-001 | HYP-001, HYP-002, HYP-005, HYP-020 |
| VAL-DICT-002 | HYP-001, HYP-005, HYP-020 |
| VAL-DICT-003 | HYP-002 |
| VAL-SET-001 | HYP-003, HYP-004, HYP-006 |
| VAL-SET-002 | HYP-003, HYP-006 |
| VAL-SET-003 | HYP-004 |
| VAL-TUPLE-001 | HYP-011 |
| VAL-STR-001 | HYP-009, HYP-024 |
| VAL-BYTES-001 | HYP-010 |
| VAL-TYPE-001 | HYP-007, HYP-008, HYP-019 |
| VAL-DUNDER-001 | HYP-012, HYP-013, HYP-021, HYP-022 |
| VAL-IMPORT-001 | HYP-014, HYP-015 |
| VAL-SCOPE-001 | HYP-014, HYP-016, HYP-017, HYP-018, HYP-023, HYP-025 |
| VAL-FILE-001 | HYP-026 |
| VAL-EXIT-001 | HYP-027 |
| VAL-INPUT-001 | HYP-028 |

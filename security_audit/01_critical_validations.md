# Critical Validations Inventory

**Date:** 2026-01-29
**Audit Phase:** 3 - Critical Validations Mapping

---

## Validation Call Graph

```
                         ┌──────────────────────────────────┐
                         │         SANDBOX STATE            │
                         │  ─────────────────────────────   │
                         │  • registered_filenames (scope)  │
                         │  • limits.* (size/count limits)  │
                         │  • suspended / suppress_checks   │
                         └────────────────┬─────────────────┘
                                          │
          ┌───────────────────────────────┼───────────────────────────────┐
          │                               │                               │
          ▼                               ▼                               ▼
   ┌─────────────────┐          ┌─────────────────┐          ┌─────────────────┐
   │  SIZE LIMITS    │          │  EXEC LIMITS    │          │  ACCESS CONTROL │
   │  ───────────    │          │  ───────────    │          │  ─────────────  │
   │ • CheckIntSize  │          │ • CheckStatement│          │ • CheckImport   │
   │ • CheckStrLen   │          │ • CheckIteration│          │ • CheckUnsafe   │
   │ • CheckBytesLen │          │ • CheckOperation│          │ • CheckDunder   │
   │ • CheckListSize │          │ • CheckAlloc    │          │ • CheckFrozen   │
   │ • CheckDictSize │          └─────────────────┘          │ • CheckType     │
   │ • CheckSetSize  │                                       │ • CheckOpcode   │
   │ • CheckTupleSize│                                       └─────────────────┘
   └─────────────────┘
```

---

## 1. Size Limit Validations

### VAL-INT-001: Integer Size Check
| Property | Value |
|----------|-------|
| ID | VAL-INT-001 |
| Function | `_PySandbox_CheckIntSize()` |
| Location | `Python/sandbox_limits.c:14-29` |
| Validates | `ndigits <= limits->max_int_digits` |
| Protects Against | Oversized integer allocation (DoS, memory exhaustion) |
| Call Sites | `Objects/longobject.c:155` (`_PyLong_New`) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion, CPU DoS via arithmetic |
| Status | ✓ **SECURED** - Single enforcement point |

### VAL-STR-001: String Length Check
| Property | Value |
|----------|-------|
| ID | VAL-STR-001 |
| Function | `_PySandbox_CheckStrLength()` |
| Location | `Python/sandbox_limits.c:32-46` |
| Validates | `length <= limits->max_str_length` |
| Protects Against | Oversized string allocation |
| Call Sites | `Objects/unicodeobject.c:1423` (`PyUnicode_New`) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ✓ **SECURED** - Single enforcement point |

### VAL-BYTES-001: Bytes Length Check
| Property | Value |
|----------|-------|
| ID | VAL-BYTES-001 |
| Function | `_PySandbox_CheckBytesLength()` |
| Location | `Python/sandbox_limits.c:48-63` |
| Validates | `length <= limits->max_bytes_length` |
| Protects Against | Oversized bytes/bytearray allocation |
| Call Sites | `Objects/bytesobject.c:101`, `Objects/bytearrayobject.c:126,200`, `Objects/bytesobject.c:1510` |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ✓ **SECURED** - Multiple enforcement points |

### VAL-LIST-001: List Size Check
| Property | Value |
|----------|-------|
| ID | VAL-LIST-001 |
| Function | `_PySandbox_CheckListSize()` |
| Location | `Python/sandbox_limits.c:66-79` |
| Validates | `size <= limits->max_list_size` |
| Protects Against | Oversized list allocation |
| Call Sites | `Objects/listobject.c:52,110,176,222` (resize, preallocate, new) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ✓ **SECURED** - All creation/resize paths covered |

### VAL-DICT-001: Dict Size Check (Insertion)
| Property | Value |
|----------|-------|
| ID | VAL-DICT-001 |
| Function | `_PySandbox_CheckDictSize()` |
| Location | `Python/sandbox_limits.c:82-95` |
| Validates | `size <= limits->max_dict_size` |
| Protects Against | Oversized dict allocation |
| Call Sites | `Objects/dictobject.c:1249,1298` (`insertdict`) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ⚠️ **PARTIAL** - Only checks insertion, NOT resize |

### VAL-DICT-002: Dict Resize (MISSING)
| Property | Value |
|----------|-------|
| ID | VAL-DICT-002 |
| Function | **NONE** |
| Location | `Objects/dictobject.c:1417` (`dictresize`) |
| Validates | **NOTHING** |
| Protects Against | Should prevent hash table growth |
| Call Sites | Called from `insertion_resize()` when dict grows |
| Dependencies | N/A |
| Severity if Bypassed | **CRITICAL** - Dict can grow indefinitely |
| Status | ❌ **MISSING VALIDATION** |

### VAL-DICT-003: Dict Copy (MISSING)
| Property | Value |
|----------|-------|
| ID | VAL-DICT-003 |
| Function | **NONE** |
| Location | `Objects/dictobject.c:3025` (`PyDict_Copy`) |
| Validates | **NOTHING** |
| Protects Against | Should prevent copying large dicts |
| Call Sites | `dict.copy()`, `dict(other_dict)` |
| Dependencies | N/A |
| Severity if Bypassed | **CRITICAL** - Can copy dicts exceeding limit |
| Status | ❌ **MISSING VALIDATION** |

### VAL-SET-001: Set Size Check (Add Entry)
| Property | Value |
|----------|-------|
| ID | VAL-SET-001 |
| Function | `_PySandbox_CheckSetSize()` |
| Location | `Python/sandbox_limits.c:98-111` |
| Validates | `size <= limits->max_set_size` |
| Protects Against | Oversized set allocation |
| Call Sites | `Objects/setobject.c:167,177` (`set_add_entry`) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ⚠️ **PARTIAL** - Only checks insertion, NOT resize |

### VAL-SET-002: Set Resize (MISSING)
| Property | Value |
|----------|-------|
| ID | VAL-SET-002 |
| Function | **NONE** |
| Location | `Objects/setobject.c:241` (`set_table_resize`) |
| Validates | **NOTHING** |
| Protects Against | Should prevent hash table growth |
| Call Sites | Called from `set_add_entry()` when set grows |
| Dependencies | N/A |
| Severity if Bypassed | **CRITICAL** - Set can grow indefinitely |
| Status | ❌ **MISSING VALIDATION** |

### VAL-SET-003: Set Copy (MISSING)
| Property | Value |
|----------|-------|
| ID | VAL-SET-003 |
| Function | **NONE** |
| Location | `Objects/setobject.c:1103` (`set_copy`) |
| Validates | **NOTHING** |
| Protects Against | Should prevent copying large sets |
| Call Sites | `set.copy()`, `frozenset(other_set)` |
| Dependencies | N/A |
| Severity if Bypassed | **HIGH** - Can copy sets exceeding limit |
| Status | ❌ **MISSING VALIDATION** |

### VAL-TUPLE-001: Tuple Size Check
| Property | Value |
|----------|-------|
| ID | VAL-TUPLE-001 |
| Function | `_PySandbox_CheckTupleSize()` |
| Location | `Python/sandbox_limits.c:114-127` |
| Validates | `size <= limits->max_tuple_size` |
| Protects Against | Oversized tuple allocation |
| Call Sites | `Objects/tupleobject.c:45` (`tuple_alloc`) |
| Dependencies | Scope check via `_PYSANDBOX_CHECK_PROLOGUE` |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ✓ **SECURED** - All paths through tuple_alloc |

---

## 2. Execution Limit Validations

### VAL-STMT-001: Statement Count Check
| Property | Value |
|----------|-------|
| ID | VAL-STMT-001 |
| Function | `_PySandbox_CheckScopeStatement()` |
| Location | `Python/sandbox_limits.c:252-283` |
| Validates | `statement_count < max_statements` |
| Protects Against | Infinite loops, CPU DoS |
| Call Sites | `Python/ceval.c` (line tracing) |
| Dependencies | Line tracing must be enabled, scope check |
| Severity if Bypassed | **HIGH** - CPU exhaustion |
| Status | ✓ **SECURED** |

### VAL-ITER-001: Iteration Count Check
| Property | Value |
|----------|-------|
| ID | VAL-ITER-001 |
| Function | `sandbox_check_iteration()` / `_PySandbox_CheckIteration()` |
| Location | `Include/internal/pycore_sandbox_impl.h:225-288` |
| Validates | `iteration_count < max_iterations` |
| Protects Against | Infinite iterator consumption |
| Call Sites | `Python/sandbox_iter.c` (iterator wrapper) |
| Dependencies | Scope check, iterator wrapper used |
| Severity if Bypassed | **HIGH** - CPU exhaustion |
| Status | ✓ **SECURED** |

### VAL-OP-001: Operation Count Check
| Property | Value |
|----------|-------|
| ID | VAL-OP-001 |
| Function | `_PySandbox_CheckScopeOperation()` |
| Location | `Python/sandbox_limits.c:302-332` |
| Validates | `operation_count < max_operations` |
| Protects Against | Expensive operations abuse |
| Call Sites | `Python/ceval.c` (SANDBOX_COUNT opcode) |
| Dependencies | Scope check, SANDBOX_COUNT opcode inserted |
| Severity if Bypassed | **HIGH** - CPU exhaustion |
| Status | ✓ **SECURED** |

### VAL-ALLOC-001: Allocation Count Check
| Property | Value |
|----------|-------|
| ID | VAL-ALLOC-001 |
| Function | `_PySandbox_CheckAllocation()` |
| Location | `Python/sandbox_limits.c:191-234` |
| Validates | `allocation_count < max_allocations` |
| Protects Against | Memory exhaustion via many small objects |
| Call Sites | `Modules/gcmodule.c` (GC tracking) |
| Dependencies | Scope check, grace headroom for error handling |
| Severity if Bypassed | **HIGH** - Memory exhaustion |
| Status | ✓ **SECURED** |

---

## 3. Access Control Validations

### VAL-IMPORT-001: Import Restriction Check
| Property | Value |
|----------|-------|
| ID | VAL-IMPORT-001 |
| Function | `_PySandbox_CheckImport()` |
| Location | `Python/sandbox_imports.c:233-359` |
| Validates | `(module, name) in allowed_imports` |
| Protects Against | Importing dangerous modules (os, subprocess, ctypes) |
| Call Sites | `Python/import.c:1836-1839` |
| Dependencies | `import_restrict_mode=1`, scope check, allowlist |
| Severity if Bypassed | **CRITICAL** - Arbitrary code execution |
| Status | ✓ **SECURED** - All import paths checked |

### VAL-UNSAFE-001: Unsafe Operation Check
| Property | Value |
|----------|-------|
| ID | VAL-UNSAFE-001 |
| Function | `_PySandbox_CheckUnsafeBlocked()` |
| Location | `Python/sandbox_limits.c:464-494` |
| Validates | `allow_unsafe=0 && operation in blocked_list` |
| Protects Against | eval(str), exec(str), compile(), gc introspection |
| Call Sites | `Python/bltinmodule.c:752,916,1018`, `Modules/gcmodule.c` |
| Dependencies | `allow_unsafe=0`, scope check |
| Severity if Bypassed | **CRITICAL** - Code execution escape |
| Status | ✓ **SECURED** |

### VAL-DUNDER-001: Dunder Attribute Access Check
| Property | Value |
|----------|-------|
| ID | VAL-DUNDER-001 |
| Function | `_PySandbox_CheckDunderAccess()` |
| Location | `Python/sandbox_limits.c:399-453` |
| Validates | `allow_dunder_access=0 && name.startswith('__')` |
| Protects Against | `__class__`, `__code__`, `__globals__` access |
| Call Sites | `Python/ceval.c` (LOAD_ATTR, STORE_ATTR, DELETE_ATTR) |
| Dependencies | `allow_dunder_access=0`, scope check |
| Severity if Bypassed | **CRITICAL** - Sandbox escape via introspection |
| Status | ⚠️ **PARTIAL** - Does not block `__builtins__` name (LOAD_NAME) |

### VAL-TYPE-001: Type Restriction Check
| Property | Value |
|----------|-------|
| ID | VAL-TYPE-001 |
| Function | `_PySandbox_CheckTypeAllowed()` |
| Location | `Python/sandbox_limits.c:130-173` |
| Validates | `allow_float/allow_complex && type matches` |
| Protects Against | float/complex creation |
| Call Sites | `Objects/typeobject.c` (type_call) |
| Dependencies | `allow_float=0` or `allow_complex=0`, scope check |
| Severity if Bypassed | **MEDIUM** - Type policy bypass |
| Status | ⚠️ **PARTIAL** - Does not block literals (compile-time) |

### VAL-FROZEN-001: Frozen Mode Check
| Property | Value |
|----------|-------|
| ID | VAL-FROZEN-001 |
| Function | `_PySandbox_CheckFrozen()` |
| Location | `Python/sandbox_frozen.c` |
| Validates | `frozen_mode=0 || obj.Py_OBJFLAGS_MUTABLE` |
| Protects Against | Mutation of external objects |
| Call Sites | `Objects/object.c` (setattr), `Objects/dictobject.c` (mutations) |
| Dependencies | `frozen_mode=1`, scope check |
| Severity if Bypassed | **HIGH** - State pollution |
| Status | ✓ **SECURED** |

### VAL-OPCODE-001: Opcode Restriction Check
| Property | Value |
|----------|-------|
| ID | VAL-OPCODE-001 |
| Function | `_PySandbox_CheckOpcode()` |
| Location | `Python/sandbox_opcodes.c:28-78` |
| Validates | `!_PySandbox_OpcodeSet_HAS(banned, opcode)` |
| Protects Against | Execution of banned opcodes |
| Call Sites | `Python/ceval.c` (opcode dispatch) |
| Dependencies | `opcode_restrict_mode=1`, scope check |
| Severity if Bypassed | **HIGH** - Policy bypass |
| Status | ✓ **SECURED** |

### VAL-CONFIG-001: Configuration Modification Check
| Property | Value |
|----------|-------|
| ID | VAL-CONFIG-001 |
| Function | `_PySandbox_CheckConfigModification()` |
| Location | `Python/sandbox_core.c` (assumed) |
| Validates | Current frame not in sandbox scope |
| Protects Against | Sandbox self-modification |
| Call Sites | `sys.sandbox` property setters |
| Dependencies | Scope check |
| Severity if Bypassed | **CRITICAL** - Sandbox disabled from within |
| Status | ✓ **SECURED** |

---

## 4. Scope Detection Mechanism

### VAL-SCOPE-001: Frame-to-Filename Scope Check
| Property | Value |
|----------|-------|
| ID | VAL-SCOPE-001 |
| Function | `frame_in_sandbox_scope()` |
| Location | `Include/internal/pycore_sandbox_impl.h:116-132` |
| Validates | `frame->f_code->co_filename in registered_filenames` |
| Protects Against | Validations being skipped |
| Used By | ALL validation functions |
| Dependencies | `registered_filenames` set populated |
| Severity if Bypassed | **CRITICAL** - All protections disabled |
| Status | ⚠️ **KEY ASSUMPTION** - Filename-based |

---

## 5. Validation Summary Table

| ID | Validation | Status | Severity if Bypassed |
|----|------------|--------|---------------------|
| VAL-INT-001 | Integer size | ✓ SECURED | HIGH |
| VAL-STR-001 | String length | ✓ SECURED | HIGH |
| VAL-BYTES-001 | Bytes length | ✓ SECURED | HIGH |
| VAL-LIST-001 | List size | ✓ SECURED | HIGH |
| VAL-DICT-001 | Dict size (insert) | ⚠️ PARTIAL | HIGH |
| VAL-DICT-002 | Dict resize | ❌ MISSING | **CRITICAL** |
| VAL-DICT-003 | Dict copy | ❌ MISSING | **CRITICAL** |
| VAL-SET-001 | Set size (add) | ⚠️ PARTIAL | HIGH |
| VAL-SET-002 | Set resize | ❌ MISSING | **CRITICAL** |
| VAL-SET-003 | Set copy | ❌ MISSING | HIGH |
| VAL-TUPLE-001 | Tuple size | ✓ SECURED | HIGH |
| VAL-STMT-001 | Statement count | ✓ SECURED | HIGH |
| VAL-ITER-001 | Iteration count | ✓ SECURED | HIGH |
| VAL-OP-001 | Operation count | ✓ SECURED | HIGH |
| VAL-ALLOC-001 | Allocation count | ✓ SECURED | HIGH |
| VAL-IMPORT-001 | Import restriction | ✓ SECURED | CRITICAL |
| VAL-UNSAFE-001 | Unsafe operations | ✓ SECURED | CRITICAL |
| VAL-DUNDER-001 | Dunder access | ⚠️ PARTIAL | CRITICAL |
| VAL-TYPE-001 | Type restriction | ⚠️ PARTIAL | MEDIUM |
| VAL-FROZEN-001 | Frozen mode | ✓ SECURED | HIGH |
| VAL-OPCODE-001 | Opcode restriction | ✓ SECURED | HIGH |
| VAL-CONFIG-001 | Config protection | ✓ SECURED | CRITICAL |
| VAL-SCOPE-001 | Scope detection | ⚠️ KEY | CRITICAL |

---

## 6. Critical Gaps Identified

### Gap 1: Dict/Set Resize Without Validation
- **VAL-DICT-002** and **VAL-SET-002** are completely missing
- Hash table resize operations bypass all sandbox checks
- Attack: Incrementally grow dict/set to exhaust memory

### Gap 2: Dict/Set Copy Without Validation
- **VAL-DICT-003** and **VAL-SET-003** are completely missing
- Can copy large containers from outside sandbox scope
- Attack: Create huge dict outside scope, copy() inside scope

### Gap 3: `__builtins__` Name Access
- **VAL-DUNDER-001** only blocks attribute access (`LOAD_ATTR`)
- `__builtins__` is accessed via `LOAD_NAME` (name lookup)
- Attack: Access `__builtins__` directly to get `__import__`

### Gap 4: Float/Complex Literals
- **VAL-TYPE-001** only blocks `float()` and `complex()` calls
- Literals like `1.5` are created at compile time
- Attack: Use literals when type is forbidden

### Gap 5: Compile-Time Constant Folding
- String/bytes multiplication like `'a' * 200` is folded at compile time
- AST optimizer limits to 4096, but sandbox limit might be lower
- Attack: Use multiplication between sandbox limit and 4096

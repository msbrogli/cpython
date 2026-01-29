# Security Audit Scope Document

**Date:** 2026-01-29
**Target:** CPython Sandbox API
**Branch:** msbrogli/sandbox
**Auditor:** Claude Security Analysis

---

## 1. Audit Objective

Identify bypass vectors and vulnerabilities in the CPython sandbox API that allow:
1. Bypassing resource limits (size limits, execution limits)
2. Bypassing import restrictions
3. Bypassing type restrictions
4. Escaping sandbox scope detection
5. Accessing forbidden operations/attributes
6. Exploiting alternative code paths that achieve the same result

---

## 2. Sandbox Overview

The sandbox provides multiple layers of protection:

### 2.1 Size Limits
- `max_int_digits` - Integer digit count
- `max_str_length` - String character count
- `max_bytes_length` - Bytes/bytearray length
- `max_list_size`, `max_dict_size`, `max_set_size`, `max_tuple_size` - Container sizes

### 2.2 Execution Limits
- `max_statements` - Statement execution count
- `max_allocations` - Object allocation count
- `max_iterations` - Iterator step count
- `max_operations` - SANDBOX_COUNT opcode count

### 2.3 Type Restrictions
- `allow_float` - Block float type creation
- `allow_complex` - Block complex type creation

### 2.4 Access Control
- `allow_dunder_access` - Block `__xxx__` attribute access
- `allow_unsafe` - Block compile/eval/exec with strings, gc introspection, __iter__

### 2.5 Import Restrictions
- `import_restrict_mode` - Enable import allowlist
- `import_allow_submodules` - Control submodule imports
- `allowed_imports` - Frozenset of (module, name) tuples

### 2.6 Object Mutation Control
- `frozen_mode` - Block all attribute mutations unless object is marked mutable
- `auto_mutable` - Auto-mark newly created objects as mutable in scope

### 2.7 Opcode Restriction
- `opcode_restrict_mode` - Enable opcode banning
- `banned_opcodes` - Set of banned opcode numbers

---

## 3. Scope Tracking Mechanism

Critical to all sandbox enforcement:
- `registered_filenames` - Set of filenames that are "in scope"
- Frame's `co_filename` checked against this set
- If frame not in scope, limits are bypassed

---

## 4. Known Vulnerabilities (from existing analysis)

| ID | Vector | Status | Severity |
|----|--------|--------|----------|
| KNOWN-01 | `open()` file access | VULNERABLE | CRITICAL |
| KNOWN-02 | Compile-time constant folding | VULNERABLE | HIGH |
| KNOWN-03 | Tuple multiplication bypass | VULNERABLE | HIGH |
| KNOWN-04 | Float/complex literals | BYPASS | HIGH |
| KNOWN-05 | `__builtins__` name access | ACCESSIBLE | HIGH |
| KNOWN-06 | `sys.exit()` | VULNERABLE | HIGH |

---

## 5. Areas to Investigate

### 5.1 Container Creation Bypasses
- Literal syntax: `[1, 2, 3]`, `{1, 2}`, `(1, 2, 3)`, `{'a': 1}`
- Constructor calls: `list()`, `dict()`, `set()`, `tuple()`
- Multiplication: `[1] * n`, `(1,) * n`
- Comprehensions: `[x for x in range(n)]`
- Conversion functions: `list(iterable)`, `tuple(iterable)`
- Built-in functions: `range()`, `zip()`, `map()`, etc.

### 5.2 Import Bypasses
- `__import__()` builtin
- `importlib.import_module()`
- `IMPORT_NAME` opcode directly
- `exec("import os")`
- Module `__loader__` access
- `sys.modules` manipulation

### 5.3 Type Restriction Bypasses
- Literal creation: `1.0`, `1+2j`
- AST constant folding
- `int.__truediv__` returning float

### 5.4 Scope Detection Bypasses
- Code from different filenames
- Dynamically generated code
- C extension callbacks
- Generator/coroutine frame switching

### 5.5 Attribute Access Bypasses
- `getattr()` vs direct attribute access
- `__class__` via type()
- `vars()`, `dir()` for introspection
- Object `__dict__` access

### 5.6 String/Bytes Creation Bypasses
- Literal multiplication: `'a' * n`, `b'a' * n`
- String methods: `str.join()`, `str.format()`
- Bytes methods: `bytes.join()`, `b''.join()`
- Encoding/decoding operations

### 5.7 Integer Creation Bypasses
- Arithmetic operations: `2 ** 1000`
- Shift operations: `1 << 1000`
- Built-in functions: `int()`, `pow()`

---

## 6. Test Categories

1. **VAL-SIZE-***: Size limit validations
2. **VAL-EXEC-***: Execution limit validations
3. **VAL-TYPE-***: Type restriction validations
4. **VAL-IMPORT-***: Import restriction validations
5. **VAL-ACCESS-***: Attribute access validations
6. **VAL-UNSAFE-***: Unsafe operation validations
7. **VAL-SCOPE-***: Scope detection validations
8. **VAL-FROZEN-***: Frozen mode validations

---

## 7. Files to Investigate

### Core Implementation
- `Python/sandbox_limits.c` - Size and execution limit checks
- `Python/sandbox_opcodes.c` - Opcode restriction
- `Python/sandbox_iter.c` - Iterator wrapper
- `Python/sandbox_frozen.c` - Frozen mode
- `Include/internal/pycore_sandbox.h` - API definitions
- `Include/internal/pycore_sandbox_impl.h` - Implementation helpers

### Validation Call Sites
- `Objects/listobject.c` - List creation/resize
- `Objects/tupleobject.c` - Tuple creation
- `Objects/dictobject.c` - Dict creation
- `Objects/setobject.c` - Set creation
- `Objects/unicodeobject.c` - String creation
- `Objects/bytesobject.c` - Bytes creation
- `Objects/bytearrayobject.c` - Bytearray creation
- `Objects/longobject.c` - Integer creation
- `Python/import.c` - Import mechanism
- `Python/bltinmodule.c` - Built-in functions
- `Python/ceval.c` - Bytecode evaluation

### AST/Compiler
- `Python/ast_opt.c` - AST optimization (constant folding)
- `Python/compile.c` - Code compilation

---

## 8. Methodology

1. Map all validation call sites in the codebase
2. For each validation, identify all code paths that could bypass it
3. Generate hypotheses for each potential bypass
4. Implement and execute tests
5. Document findings

---

## 9. Success Criteria

A bypass is confirmed when:
1. Sandbox limits/restrictions are configured
2. A filename is registered (in scope)
3. Code achieves a result that should have been blocked
4. No exception is raised

---

## 10. Out of Scope

- OS-level sandboxing (seccomp, namespaces, containers)
- Network-based attacks
- Hardware-level attacks
- Social engineering

# SANDBOX_COUNT AST Operations Count Tests

This directory contains a comprehensive test framework for verifying the RFC-011 AST operations count implementation. The tests verify that SANDBOX_COUNT opcodes are correctly emitted based on the `operations_count` attribute of AST nodes.

## Overview

The test framework consists of:

1. **Test Cases** (`testcases/`): Python source code files organized by complexity
   - `simple/`: Basic operations (pass, assignments, binary ops, etc.)
   - `medium/`: Control flow, loops, functions, classes
   - `complex/`: Constant folding, nested structures, comprehensions, etc.

2. **Bytecode Extractor** (`bytecode_extract.py`): Utility to extract SANDBOX_COUNT opcodes from compiled Python code

3. **Test Runner** (`test_runner.py`): Main test execution script

## Usage

### List Available Tests
```bash
python Lib/test/sandbox_ast_ops/test_runner.py --list
```

### Run All Tests
```bash
python Lib/test/sandbox_ast_ops/test_runner.py
```

### Generate Expected Outputs
First, you need to generate expected bytecode outputs for all test cases:
```bash
python Lib/test/sandbox_ast_ops/test_runner.py --generate
```

This creates `.expected` files next to each test case. These files contain the expected SANDBOX_COUNT opcodes.

### Test AST Optimizer Consistency
Verify that the sum of operations counts is consistent with and without AST optimization:
```bash
python Lib/test/sandbox_ast_ops/test_runner.py --optimizer-check
```

Note: For constant folding tests, different counts are expected (optimization reduces the count).

### Run Specific Test
```bash
python Lib/test/sandbox_ast_ops/test_runner.py testcases/simple/01_pass.py
```

### Extract Bytecode from Source
```bash
python Lib/test/sandbox_ast_ops/bytecode_extract.py testcases/simple/01_pass.py
```

## Test Case Format

Each test case is a Python source file with:
1. Comments describing what is being tested
2. Simple Python code that exercises specific AST node types
3. Expected bytecode output (in `.expected` file after generation)

Example test case:
```python
# Test: pass statement
# A pass statement should count as 1 operation
pass
```

Expected output format:
```
   0: SANDBOX_COUNT        1

Total operations count: 1
```

## What Gets Counted

According to RFC-011, the following AST nodes have `operations_count=1`:

### Statements
- FunctionDef, AsyncFunctionDef
- ClassDef
- Return
- Delete
- Assign, AugAssign, AnnAssign
- For, AsyncFor
- While
- If
- With, AsyncWith
- Match
- Raise
- Try, TryStar
- Assert
- Import, ImportFrom
- Pass
- Break, Continue

### Expressions
- BoolOp
- BinOp
- UnaryOp
- Compare
- Call
- Attribute
- Subscript
- Dict, Set, List, Tuple

## Constant Folding

When the AST optimizer folds constant expressions, it accumulates the operation counts:

- `1 + 2` → `3` with count=1
- `(1 + 2) * 3` → `9` with count=2
- `(1 + 2) * (3 + 4)` → `21` with count=3
- `-(-5)` → `5` with count=2

The test runner's `--optimizer-check` mode verifies this behavior.

## Adding New Test Cases

1. Create a new `.py` file in the appropriate `testcases/` subdirectory
2. Add comments explaining what is being tested
3. Write minimal Python code exercising the feature
4. Run `test_runner.py --generate` to create the expected output
5. Verify the expected output is correct
6. Run `test_runner.py` to confirm the test passes

## Implementation Details

The test framework uses Python's `compile()` function with the `PyCF_SANDBOX_COUNT` flag to compile source code with SANDBOX_COUNT opcodes enabled. The `dis` module is used to extract the bytecode.

Key constants:
- `PyCF_SANDBOX_COUNT = 0x8000` (from `Include/cpython/compile.h`)

## Integration with Python Test Suite

To integrate with the main Python test suite, add to `Lib/test/test_sandbox_ast_ops.py`:

```python
import unittest
import sys
from pathlib import Path

class TestSandboxASTOps(unittest.TestCase):
    def test_all_cases(self):
        runner_path = Path(__file__).parent / "sandbox_ast_ops/test_runner.py"
        result = subprocess.run([sys.executable, str(runner_path)],
                              capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
```

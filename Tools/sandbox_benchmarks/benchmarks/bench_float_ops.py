"""Benchmark: Float operations.

Exercises _PySandbox_CheckTypeAllowed for float/complex types.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
import math

def float_arithmetic():
    \"\"\"Basic float arithmetic.\"\"\"
    x = 1.0
    i = 0
    while i < 10000:
        x = x + 0.1
        x = x * 1.01
        x = x - 0.05
        x = x / 1.001
        i += 1
    return x

def float_math_funcs():
    \"\"\"Math module function calls.\"\"\"
    i = 0
    while i < 5000:
        x = math.sqrt(2.0)
        x = math.sin(1.5)
        x = math.cos(1.5)
        x = math.log(100.0)
        x = math.exp(2.0)
        x = math.floor(3.7)
        i += 1
    return x

def float_create():
    \"\"\"Float creation from various sources.\"\"\"
    i = 0
    while i < 10000:
        x = float(42)
        x = float("3.14")
        x = float(True)
        x = 1.0 + 2.0
        i += 1
    return x

def float_comparison():
    \"\"\"Float comparison operations.\"\"\"
    a = 3.14
    b = 2.71
    i = 0
    while i < 10000:
        _ = a < b
        _ = a > b
        _ = a == b
        _ = a != b
        _ = a <= b
        _ = a >= b
        i += 1
    return True

def float_conversion():
    \"\"\"Float to/from int conversion.\"\"\"
    i = 0
    while i < 10000:
        x = int(3.14)
        y = float(42)
        x = int(99.9)
        y = float(x)
        i += 1
    return y

def float_list_ops():
    \"\"\"Operations on lists of floats.\"\"\"
    data = [float(x) * 0.1 for x in range(100)]
    i = 0
    while i < 2000:
        s = sum(data)
        mn = min(data)
        mx = max(data)
        i += 1
    return s
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('float_arithmetic', ns['float_arithmetic'])
    runner.bench_func('float_math_funcs', ns['float_math_funcs'])
    runner.bench_func('float_create', ns['float_create'])
    runner.bench_func('float_comparison', ns['float_comparison'])
    runner.bench_func('float_conversion', ns['float_conversion'])
    runner.bench_func('float_list_ops', ns['float_list_ops'])

"""Benchmark: Integer arithmetic operations.

Exercises _PySandbox_CheckIntSize on _PyLong_New for various int sizes.
Uses while-loops to avoid iteration wrapper overhead.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args, SANDBOX_FILENAME

SOURCE = """
def int_add_small():
    \"\"\"Add small integers (fit in single digit).\"\"\"
    x = 0
    i = 0
    while i < 10000:
        x = x + 7
        x = x + 13
        x = x - 5
        x = x + 3
        i += 1
    return x

def int_add_medium():
    \"\"\"Add medium integers (multiple digits).\"\"\"
    x = 10**50
    y = 10**50 + 999
    i = 0
    while i < 5000:
        x = x + y
        x = x - y
        x = x + y
        x = x - y
        i += 1
    return x

def int_mul_small():
    \"\"\"Multiply small integers.\"\"\"
    x = 1
    i = 0
    while i < 10000:
        x = 7 * 13
        x = 100 * 99
        x = 42 * 58
        x = 256 * 256
        i += 1
    return x

def int_mul_medium():
    \"\"\"Multiply medium integers.\"\"\"
    a = 10**30
    b = 10**30 + 1
    i = 0
    while i < 2000:
        x = a * b
        i += 1
    return x

def int_pow_small():
    \"\"\"Power with small base and exponent.\"\"\"
    i = 0
    while i < 5000:
        x = 2 ** 30
        x = 3 ** 20
        x = 7 ** 10
        i += 1
    return x

def int_divmod():
    \"\"\"Division and modulo operations.\"\"\"
    a = 10**18
    b = 997
    i = 0
    while i < 10000:
        q = a // b
        r = a % b
        q, r = divmod(a, b)
        i += 1
    return q
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('int_add_small', ns['int_add_small'])
    runner.bench_func('int_add_medium', ns['int_add_medium'])
    runner.bench_func('int_mul_small', ns['int_mul_small'])
    runner.bench_func('int_mul_medium', ns['int_mul_medium'])
    runner.bench_func('int_pow_small', ns['int_pow_small'])
    runner.bench_func('int_divmod', ns['int_divmod'])

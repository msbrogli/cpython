"""Benchmark: Tuple operations.

Exercises _PySandbox_CheckTupleSize.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def tuple_create():
    \"\"\"Tuple creation.\"\"\"
    i = 0
    while i < 10000:
        t = (1, 2, 3, 4, 5)
        t = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
        t = tuple(range(20))
        i += 1
    return t

def tuple_concat():
    \"\"\"Tuple concatenation.\"\"\"
    a = (1, 2, 3, 4, 5)
    b = (6, 7, 8, 9, 10)
    i = 0
    while i < 10000:
        t = a + b
        t = a + b + a
        i += 1
    return t

def tuple_unpack():
    \"\"\"Tuple unpacking.\"\"\"
    t = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
    i = 0
    while i < 10000:
        a, b, c, d, e, f, g, h, j, k = t
        first, *rest = t
        *init, last = t
        i += 1
    return a

def tuple_slice():
    \"\"\"Tuple slicing.\"\"\"
    t = tuple(range(100))
    i = 0
    while i < 5000:
        s = t[10:50]
        s = t[:25]
        s = t[75:]
        s = t[::2]
        i += 1
    return s

def tuple_index_access():
    \"\"\"Tuple indexing.\"\"\"
    t = tuple(range(100))
    i = 0
    while i < 10000:
        x = t[0]
        x = t[50]
        x = t[99]
        x = t[-1]
        x = t[-50]
        i += 1
    return x

def tuple_contains():
    \"\"\"Tuple membership testing.\"\"\"
    t = tuple(range(100))
    i = 0
    while i < 5000:
        _ = 0 in t
        _ = 50 in t
        _ = 99 in t
        _ = 999 in t
        i += 1
    return True
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('tuple_create', ns['tuple_create'])
    runner.bench_func('tuple_concat', ns['tuple_concat'])
    runner.bench_func('tuple_unpack', ns['tuple_unpack'])
    runner.bench_func('tuple_slice', ns['tuple_slice'])
    runner.bench_func('tuple_index_access', ns['tuple_index_access'])
    runner.bench_func('tuple_contains', ns['tuple_contains'])

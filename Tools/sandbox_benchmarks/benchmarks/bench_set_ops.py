"""Benchmark: Set operations.

Exercises _PySandbox_CheckSetSize on add.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def set_add():
    \"\"\"Set add in a loop.\"\"\"
    i = 0
    while i < 500:
        s = set()
        j = 0
        while j < 1000:
            s.add(j)
            j += 1
        i += 1
    return s

def set_union():
    \"\"\"Set union operations.\"\"\"
    a = set(range(500))
    b = set(range(250, 750))
    i = 0
    while i < 3000:
        c = a | b
        c = a.union(b)
        i += 1
    return c

def set_intersection():
    \"\"\"Set intersection operations.\"\"\"
    a = set(range(500))
    b = set(range(250, 750))
    i = 0
    while i < 3000:
        c = a & b
        c = a.intersection(b)
        i += 1
    return c

def set_difference():
    \"\"\"Set difference operations.\"\"\"
    a = set(range(500))
    b = set(range(250, 750))
    i = 0
    while i < 3000:
        c = a - b
        c = a.difference(b)
        i += 1
    return c

def set_contains():
    \"\"\"Set membership testing.\"\"\"
    s = set(range(1000))
    i = 0
    while i < 10000:
        _ = 0 in s
        _ = 500 in s
        _ = 999 in s
        _ = 9999 in s
        i += 1
    return True

def set_comprehension():
    \"\"\"Set comprehension.\"\"\"
    i = 0
    while i < 1000:
        s = {x * 2 for x in range(500)}
        i += 1
    return s
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('set_add', ns['set_add'])
    runner.bench_func('set_union', ns['set_union'])
    runner.bench_func('set_intersection', ns['set_intersection'])
    runner.bench_func('set_difference', ns['set_difference'])
    runner.bench_func('set_contains', ns['set_contains'])
    runner.bench_func('set_comprehension', ns['set_comprehension'])

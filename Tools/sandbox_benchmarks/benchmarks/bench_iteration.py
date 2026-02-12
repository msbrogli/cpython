"""Benchmark: Iteration operations.

Exercises _PySandbox_WrapIterator + per-yield check.
This benchmark deliberately uses for-loops and iterators to measure
the overhead of iterator wrapping.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def iter_for_range():
    \"\"\"for loop over range().\"\"\"
    s = 0
    i = 0
    while i < 200:
        for x in range(1000):
            s += x
        i += 1
    return s

def iter_for_list():
    \"\"\"for loop over a list.\"\"\"
    data = list(range(1000))
    s = 0
    i = 0
    while i < 200:
        for x in data:
            s += x
        i += 1
    return s

def iter_generator():
    \"\"\"Generator iteration.\"\"\"
    def gen(n):
        i = 0
        while i < n:
            yield i
            i += 1

    s = 0
    i = 0
    while i < 200:
        for x in gen(1000):
            s += x
        i += 1
    return s

def iter_list_comprehension():
    \"\"\"List comprehension iteration.\"\"\"
    i = 0
    while i < 500:
        result = [x * 2 for x in range(1000)]
        i += 1
    return result

def iter_dict_comprehension():
    \"\"\"Dict comprehension iteration.\"\"\"
    i = 0
    while i < 500:
        result = {x: x * 2 for x in range(500)}
        i += 1
    return result

def iter_zip():
    \"\"\"zip iteration.\"\"\"
    a = list(range(1000))
    b = list(range(1000, 2000))
    s = 0
    i = 0
    while i < 200:
        for x, y in zip(a, b):
            s += x + y
        i += 1
    return s

def iter_enumerate():
    \"\"\"enumerate iteration.\"\"\"
    data = list(range(1000))
    s = 0
    i = 0
    while i < 200:
        for idx, val in enumerate(data):
            s += idx + val
        i += 1
    return s

def iter_map():
    \"\"\"map() iteration.\"\"\"
    data = list(range(1000))
    i = 0
    while i < 200:
        result = list(map(lambda x: x * 2, data))
        i += 1
    return result

def iter_filter():
    \"\"\"filter() iteration.\"\"\"
    data = list(range(1000))
    i = 0
    while i < 200:
        result = list(filter(lambda x: x % 2 == 0, data))
        i += 1
    return result

def iter_nested():
    \"\"\"Nested iteration.\"\"\"
    s = 0
    i = 0
    while i < 50:
        for x in range(100):
            for y in range(100):
                s += x + y
        i += 1
    return s
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('iter_for_range', ns['iter_for_range'])
    runner.bench_func('iter_for_list', ns['iter_for_list'])
    runner.bench_func('iter_generator', ns['iter_generator'])
    runner.bench_func('iter_list_comprehension', ns['iter_list_comprehension'])
    runner.bench_func('iter_dict_comprehension', ns['iter_dict_comprehension'])
    runner.bench_func('iter_zip', ns['iter_zip'])
    runner.bench_func('iter_enumerate', ns['iter_enumerate'])
    runner.bench_func('iter_map', ns['iter_map'])
    runner.bench_func('iter_filter', ns['iter_filter'])
    runner.bench_func('iter_nested', ns['iter_nested'])

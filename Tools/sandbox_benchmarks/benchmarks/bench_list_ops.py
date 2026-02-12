"""Benchmark: List operations.

Exercises _PySandbox_CheckListSize on growth.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def list_append():
    \"\"\"List append in a loop.\"\"\"
    i = 0
    while i < 500:
        lst = []
        j = 0
        while j < 1000:
            lst.append(j)
            j += 1
        i += 1
    return lst

def list_comprehension():
    \"\"\"List comprehension (creates list).\"\"\"
    i = 0
    while i < 1000:
        lst = [x * 2 for x in range(500)]
        i += 1
    return lst

def list_extend():
    \"\"\"List extend operations.\"\"\"
    base = list(range(100))
    extra = list(range(100, 200))
    i = 0
    while i < 2000:
        lst = base[:]
        lst.extend(extra)
        lst.extend(extra)
        i += 1
    return lst

def list_sort():
    \"\"\"List sort (in-place).\"\"\"
    import random
    rng = random.Random(42)
    data = [rng.random() for _ in range(1000)]
    i = 0
    while i < 500:
        lst = data[:]
        lst.sort()
        i += 1
    return lst

def list_copy():
    \"\"\"List copy operations.\"\"\"
    data = list(range(1000))
    i = 0
    while i < 5000:
        lst = data[:]
        lst = list(data)
        lst = data.copy()
        i += 1
    return lst

def list_index_access():
    \"\"\"List indexing (get/set).\"\"\"
    data = list(range(1000))
    i = 0
    while i < 5000:
        x = data[0]
        x = data[500]
        x = data[-1]
        data[0] = 999
        data[500] = 999
        data[0] = 0
        data[500] = 500
        i += 1
    return x

def list_pop():
    \"\"\"List pop operations.\"\"\"
    i = 0
    while i < 500:
        lst = list(range(500))
        j = 0
        while j < 250:
            lst.pop()
            j += 1
        i += 1
    return lst
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('list_append', ns['list_append'])
    runner.bench_func('list_comprehension', ns['list_comprehension'])
    runner.bench_func('list_extend', ns['list_extend'])
    runner.bench_func('list_sort', ns['list_sort'])
    runner.bench_func('list_copy', ns['list_copy'])
    runner.bench_func('list_index_access', ns['list_index_access'])
    runner.bench_func('list_pop', ns['list_pop'])

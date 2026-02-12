"""Benchmark: Dict operations.

Exercises _PySandbox_CheckDictSize on insert.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def dict_insert():
    \"\"\"Dict insert in a loop.\"\"\"
    i = 0
    while i < 500:
        d = {}
        j = 0
        while j < 1000:
            d[j] = j
            j += 1
        i += 1
    return d

def dict_comprehension():
    \"\"\"Dict comprehension.\"\"\"
    i = 0
    while i < 1000:
        d = {x: x * 2 for x in range(500)}
        i += 1
    return d

def dict_update():
    \"\"\"Dict update operations.\"\"\"
    base = {i: i for i in range(200)}
    extra = {i: i * 2 for i in range(100, 300)}
    i = 0
    while i < 2000:
        d = base.copy()
        d.update(extra)
        i += 1
    return d

def dict_lookup():
    \"\"\"Dict key lookup.\"\"\"
    d = {i: i for i in range(1000)}
    i = 0
    while i < 5000:
        x = d[0]
        x = d[500]
        x = d[999]
        _ = d.get(42)
        _ = d.get(9999, -1)
        i += 1
    return x

def dict_copy():
    \"\"\"Dict copy operations.\"\"\"
    data = {i: i for i in range(1000)}
    i = 0
    while i < 3000:
        d = data.copy()
        d = dict(data)
        i += 1
    return d

def dict_delete():
    \"\"\"Dict delete operations.\"\"\"
    i = 0
    while i < 500:
        d = {j: j for j in range(500)}
        j = 0
        while j < 250:
            del d[j]
            j += 1
        i += 1
    return d

def dict_iterate_keys():
    \"\"\"Dict key iteration.\"\"\"
    d = {i: i for i in range(1000)}
    i = 0
    while i < 2000:
        s = 0
        for k in d:
            s += k
        i += 1
    return s
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('dict_insert', ns['dict_insert'])
    runner.bench_func('dict_comprehension', ns['dict_comprehension'])
    runner.bench_func('dict_update', ns['dict_update'])
    runner.bench_func('dict_lookup', ns['dict_lookup'])
    runner.bench_func('dict_copy', ns['dict_copy'])
    runner.bench_func('dict_delete', ns['dict_delete'])
    runner.bench_func('dict_iterate_keys', ns['dict_iterate_keys'])

"""Benchmark: Opcode counting overhead.

Compares code compiled with vs without PyCF_SANDBOX_COUNT=0x8000.
Measures the overhead of the SANDBOX_COUNT opcode in the dispatch loop.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, add_common_args, SANDBOX_FILENAME, HAS_SANDBOX

# Source code for benchmark workloads
WORKLOAD_SOURCE = """
def tight_loop():
    s = 0
    i = 0
    while i < 50000:
        s += i
        i += 1
    return s

def arithmetic_heavy():
    x = 0
    i = 0
    while i < 10000:
        x = x + 7
        x = x * 3
        x = x - 5
        x = x + 11
        x = x - 3
        x = x % 10000
        i += 1
    return x

def function_call_heavy():
    def add(a, b):
        return a + b

    def mul(a, b):
        return a * b

    s = 0
    i = 0
    while i < 5000:
        s = add(s, 1)
        s = mul(s, 1)
        s = add(s, 2)
        s = mul(s, 1)
        i += 1
    return s

def mixed_operations():
    result = []
    d = {}
    i = 0
    while i < 2000:
        result.append(i * 2)
        d[str(i)] = i
        x = len(result)
        y = i ** 2
        z = x + y
        i += 1
    return len(result), len(d)
"""

# PyCF_SANDBOX_COUNT flag value
PyCF_SANDBOX_COUNT = 0x8000


def make_funcs_normal():
    """Compile without SANDBOX_COUNT flag."""
    code = compile(WORKLOAD_SOURCE, SANDBOX_FILENAME, "exec")
    ns = {}
    exec(code, ns)
    return ns


def make_funcs_counted():
    """Compile with SANDBOX_COUNT flag (adds opcount instrumentation)."""
    code = compile(WORKLOAD_SOURCE, SANDBOX_FILENAME, "exec",
                   flags=PyCF_SANDBOX_COUNT)
    ns = {}
    exec(code, ns)
    return ns


if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    # Compile workloads both ways
    ns_normal = make_funcs_normal()
    ns_counted = make_funcs_counted()

    func_names = ['tight_loop', 'arithmetic_heavy',
                  'function_call_heavy', 'mixed_operations']

    for name in func_names:
        runner.bench_func(f'{name}_normal', ns_normal[name])
        runner.bench_func(f'{name}_counted', ns_counted[name])

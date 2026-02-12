"""Benchmark: Function call operations.

Exercises DISPATCH overhead and recursion tracking.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def _empty():
    pass

def _with_args(a, b, c):
    return a

def _with_kwargs(a=1, b=2, c=3):
    return a

def _with_mixed(a, b, c=3, d=4):
    return a

class Obj:
    def method(self):
        pass
    def method_args(self, a, b):
        return a

_obj = Obj()

def call_empty():
    \"\"\"Call empty function.\"\"\"
    f = _empty
    i = 0
    while i < 10000:
        f()
        f()
        f()
        f()
        f()
        i += 1

def call_with_args():
    \"\"\"Call function with positional args.\"\"\"
    f = _with_args
    i = 0
    while i < 10000:
        f(1, 2, 3)
        f(1, 2, 3)
        f(1, 2, 3)
        f(1, 2, 3)
        f(1, 2, 3)
        i += 1

def call_with_kwargs():
    \"\"\"Call function with keyword args.\"\"\"
    f = _with_kwargs
    i = 0
    while i < 10000:
        f(a=1, b=2, c=3)
        f(a=1, b=2, c=3)
        f(a=1, b=2, c=3)
        i += 1

def call_with_mixed():
    \"\"\"Call function with mixed args.\"\"\"
    f = _with_mixed
    i = 0
    while i < 10000:
        f(1, 2, c=3, d=4)
        f(1, 2, c=3, d=4)
        f(1, 2, c=3, d=4)
        i += 1

def call_builtin():
    \"\"\"Call builtin functions.\"\"\"
    i = 0
    while i < 5000:
        len("hello")
        abs(-42)
        isinstance(42, int)
        min(1, 2)
        max(3, 4)
        i += 1

def call_method():
    \"\"\"Call object methods.\"\"\"
    o = _obj
    i = 0
    while i < 10000:
        o.method()
        o.method()
        o.method()
        o.method_args(1, 2)
        o.method_args(1, 2)
        i += 1

def call_recursive():
    \"\"\"Recursive function calls.\"\"\"
    def fib(n):
        if n <= 1:
            return n
        return fib(n - 1) + fib(n - 2)

    i = 0
    while i < 200:
        fib(15)
        i += 1

def call_lambda():
    \"\"\"Lambda function calls.\"\"\"
    f = lambda x: x + 1
    g = lambda x, y: x * y
    i = 0
    while i < 10000:
        f(1)
        f(2)
        g(3, 4)
        g(5, 6)
        i += 1

def call_closure():
    \"\"\"Closure function calls.\"\"\"
    def make_adder(n):
        def adder(x):
            return x + n
        return adder

    add5 = make_adder(5)
    add10 = make_adder(10)
    i = 0
    while i < 10000:
        add5(1)
        add10(2)
        add5(3)
        add10(4)
        i += 1
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('call_empty', ns['call_empty'])
    runner.bench_func('call_with_args', ns['call_with_args'])
    runner.bench_func('call_with_kwargs', ns['call_with_kwargs'])
    runner.bench_func('call_with_mixed', ns['call_with_mixed'])
    runner.bench_func('call_builtin', ns['call_builtin'])
    runner.bench_func('call_method', ns['call_method'])
    runner.bench_func('call_recursive', ns['call_recursive'])
    runner.bench_func('call_lambda', ns['call_lambda'])
    runner.bench_func('call_closure', ns['call_closure'])

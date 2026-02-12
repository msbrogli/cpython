"""Benchmark: Bytes operations.

Exercises _PySandbox_CheckBytesLength.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def bytes_concat():
    \"\"\"Bytes concatenation via +.\"\"\"
    i = 0
    while i < 5000:
        b = b"hello" + b" " + b"world"
        b = b"foo" + b"bar" + b"baz" + b"qux"
        i += 1
    return b

def bytes_join():
    \"\"\"Bytes join operations.\"\"\"
    parts = [b"the", b"quick", b"brown", b"fox", b"jumps"]
    i = 0
    while i < 5000:
        b = b" ".join(parts)
        b = b",".join(parts)
        b = b"".join(parts)
        i += 1
    return b

def bytes_split():
    \"\"\"Bytes split operations.\"\"\"
    data = b"the quick brown fox jumps over the lazy dog"
    i = 0
    while i < 5000:
        parts = data.split()
        parts = data.split(b" ")
        parts = b"a,b,c,d,e".split(b",")
        i += 1
    return parts

def bytes_from_list():
    \"\"\"Create bytes from list of ints.\"\"\"
    vals = list(range(256))
    i = 0
    while i < 2000:
        b = bytes(vals)
        i += 1
    return b

def bytes_decode():
    \"\"\"Bytes decode operations.\"\"\"
    data = b"the quick brown fox jumps over the lazy dog"
    i = 0
    while i < 5000:
        s = data.decode("utf-8")
        s = data.decode("ascii")
        b = s.encode("utf-8")
        i += 1
    return b

def bytearray_ops():
    \"\"\"Bytearray append and extend.\"\"\"
    i = 0
    while i < 1000:
        ba = bytearray()
        j = 0
        while j < 200:
            ba.append(j % 256)
            j += 1
        ba.extend(b"extra data here")
        i += 1
    return ba
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('bytes_concat', ns['bytes_concat'])
    runner.bench_func('bytes_join', ns['bytes_join'])
    runner.bench_func('bytes_split', ns['bytes_split'])
    runner.bench_func('bytes_from_list', ns['bytes_from_list'])
    runner.bench_func('bytes_decode', ns['bytes_decode'])
    runner.bench_func('bytearray_ops', ns['bytearray_ops'])

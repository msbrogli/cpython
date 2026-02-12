"""Benchmark: String operations.

Exercises _PySandbox_CheckStrLength on PyUnicode_New.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
def str_concat():
    \"\"\"String concatenation via +.\"\"\"
    s = ""
    i = 0
    while i < 5000:
        s = "hello" + " " + "world"
        s = "foo" + "bar" + "baz" + "qux"
        i += 1
    return s

def str_join():
    \"\"\"String join operations.\"\"\"
    words = ["the", "quick", "brown", "fox", "jumps", "over", "the", "lazy", "dog"]
    i = 0
    while i < 5000:
        s = " ".join(words)
        s = ",".join(words)
        s = "".join(words)
        i += 1
    return s

def str_split():
    \"\"\"String split operations.\"\"\"
    text = "the quick brown fox jumps over the lazy dog"
    i = 0
    while i < 5000:
        parts = text.split()
        parts = text.split(" ")
        parts = "a,b,c,d,e,f".split(",")
        i += 1
    return parts

def str_format():
    \"\"\"String formatting operations.\"\"\"
    name = "world"
    num = 42
    i = 0
    while i < 5000:
        s = "hello %s %d" % (name, num)
        s = "hello {} {}".format(name, num)
        s = f"hello {name} {num}"
        i += 1
    return s

def str_replace():
    \"\"\"String replace operations.\"\"\"
    text = "the quick brown fox jumps over the quick brown dog"
    i = 0
    while i < 5000:
        s = text.replace("quick", "slow")
        s = text.replace("brown", "red")
        s = text.replace("the", "a")
        i += 1
    return s

def str_encode():
    \"\"\"String encode/decode operations.\"\"\"
    text = "the quick brown fox jumps over the lazy dog"
    i = 0
    while i < 5000:
        b = text.encode("utf-8")
        s = b.decode("utf-8")
        b = text.encode("ascii")
        s = b.decode("ascii")
        i += 1
    return s

def str_startswith():
    \"\"\"String startswith/endswith/find.\"\"\"
    text = "the quick brown fox jumps over the lazy dog"
    i = 0
    while i < 10000:
        text.startswith("the")
        text.endswith("dog")
        text.find("fox")
        text.index("jumps")
        i += 1
    return True
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('str_concat', ns['str_concat'])
    runner.bench_func('str_join', ns['str_join'])
    runner.bench_func('str_split', ns['str_split'])
    runner.bench_func('str_format', ns['str_format'])
    runner.bench_func('str_replace', ns['str_replace'])
    runner.bench_func('str_encode', ns['str_encode'])
    runner.bench_func('str_startswith', ns['str_startswith'])

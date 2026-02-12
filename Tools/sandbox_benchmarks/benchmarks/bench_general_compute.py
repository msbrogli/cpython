"""Benchmark: General compute (macro-benchmarks).

Realistic combined workloads that exercise multiple sandbox check paths.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyperf
from bench_utils import setup_sandbox, make_bench_funcs, add_common_args

SOURCE = """
import math
import json
import re

def fibonacci():
    \"\"\"Fibonacci computation (recursive with memoization).\"\"\"
    def fib(n, memo={}):
        if n in memo:
            return memo[n]
        if n <= 1:
            return n
        memo[n] = fib(n - 1, memo) + fib(n - 2, memo)
        return memo[n]

    i = 0
    while i < 500:
        memo = {}
        fib.__defaults__ = (memo,)
        result = fib(80)
        i += 1
    return result

def fibonacci_iterative():
    \"\"\"Fibonacci computation (iterative).\"\"\"
    i = 0
    while i < 1000:
        a, b = 0, 1
        j = 0
        while j < 100:
            a, b = b, a + b
            j += 1
        i += 1
    return b

def nbody():
    \"\"\"N-body simulation (simplified).\"\"\"
    # 5 bodies with (x, y, z, vx, vy, vz, mass)
    bodies = [
        [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0],  # sun
        [4.841, -1.160, -0.104, 0.00166, 0.00769, -0.0000690, 0.000954],
        [8.343, 4.124, -0.403, -0.00276, 0.00499, 0.0000230, 0.000286],
        [-15.53, -25.22, 0.179, 0.00297, -0.00111, -0.0000322, 0.0000437],
        [-30.16, -1.591, 1.680, 0.000268, -0.00325, 0.0000201, 0.0000517],
    ]
    dt = 0.01
    n = len(bodies)

    loops = 0
    while loops < 50:
        # Copy bodies for this iteration
        b = [row[:] for row in bodies]
        step = 0
        while step < 100:
            # Update velocities
            bi = 0
            while bi < n:
                bj = bi + 1
                while bj < n:
                    dx = b[bi][0] - b[bj][0]
                    dy = b[bi][1] - b[bj][1]
                    dz = b[bi][2] - b[bj][2]
                    dist2 = dx*dx + dy*dy + dz*dz
                    mag = dt / (dist2 * math.sqrt(dist2))
                    b[bi][3] -= dx * b[bj][6] * mag
                    b[bi][4] -= dy * b[bj][6] * mag
                    b[bi][5] -= dz * b[bj][6] * mag
                    b[bj][3] += dx * b[bi][6] * mag
                    b[bj][4] += dy * b[bi][6] * mag
                    b[bj][5] += dz * b[bi][6] * mag
                    bj += 1
                bi += 1
            # Update positions
            bi = 0
            while bi < n:
                b[bi][0] += dt * b[bi][3]
                b[bi][1] += dt * b[bi][4]
                b[bi][2] += dt * b[bi][5]
                bi += 1
            step += 1
        loops += 1
    return b[0][0]

def spectral_norm():
    \"\"\"Spectral norm computation (simplified).\"\"\"
    n = 50

    def eval_a(i, j):
        return 1.0 / ((i + j) * (i + j + 1) // 2 + i + 1)

    def eval_a_times_u(u):
        n = len(u)
        result = [0.0] * n
        i = 0
        while i < n:
            s = 0.0
            j = 0
            while j < n:
                s += eval_a(i, j) * u[j]
                j += 1
            result[i] = s
            i += 1
        return result

    def eval_at_times_u(u):
        n = len(u)
        result = [0.0] * n
        i = 0
        while i < n:
            s = 0.0
            j = 0
            while j < n:
                s += eval_a(j, i) * u[j]
                j += 1
            result[i] = s
            i += 1
        return result

    loops = 0
    while loops < 100:
        u = [1.0] * n
        k = 0
        while k < 5:
            v = eval_a_times_u(u)
            u = eval_at_times_u(v)
            k += 1

        vBv = 0.0
        vv = 0.0
        i = 0
        while i < n:
            vBv += u[i] * v[i]
            vv += v[i] * v[i]
            i += 1
        result = math.sqrt(vBv / vv)
        loops += 1
    return result

def fannkuch():
    \"\"\"Fannkuch benchmark (small n).\"\"\"
    n = 7

    def run_fannkuch(n):
        perm = list(range(n))
        count = [0] * n
        max_flips = 0
        checksum = 0
        perm_count = 0

        r = n
        while True:
            while r > 1:
                count[r - 1] = r
                r -= 1

            # Count flips
            p0 = perm[0]
            if p0 != 0:
                pp = perm[:]
                flips = 0
                while pp[0] != 0:
                    k = pp[0]
                    # Reverse first k+1 elements
                    i = 0
                    j = k
                    while i < j:
                        pp[i], pp[j] = pp[j], pp[i]
                        i += 1
                        j -= 1
                    flips += 1
                if flips > max_flips:
                    max_flips = flips
                if perm_count % 2 == 0:
                    checksum += flips
                else:
                    checksum -= flips

            perm_count += 1

            # Generate next permutation
            while True:
                if r >= n:
                    return max_flips, checksum
                perm.insert(r, perm.pop(0))
                count[r] -= 1
                if count[r] > 0:
                    break
                r += 1

    loops = 0
    while loops < 50:
        result = run_fannkuch(n)
        loops += 1
    return result

def json_encode_decode():
    \"\"\"JSON encode/decode operations.\"\"\"
    data = {
        "name": "benchmark",
        "values": list(range(100)),
        "nested": {
            "a": [1, 2, 3],
            "b": {"x": 1.5, "y": 2.5},
            "c": "hello world",
        },
        "flags": [True, False, True, None],
    }
    i = 0
    while i < 1000:
        s = json.dumps(data)
        d = json.loads(s)
        s = json.dumps(d, sort_keys=True)
        d = json.loads(s)
        i += 1
    return d

def regex_ops():
    \"\"\"Regular expression operations.\"\"\"
    pattern = re.compile(r'(\\w+)@(\\w+)\\.(\\w+)')
    text = "Contact us at user@example.com or admin@test.org for info"
    pattern2 = re.compile(r'\\b\\d{3}-\\d{4}\\b')
    text2 = "Call 555-1234 or 555-5678 for details"

    i = 0
    while i < 2000:
        m = pattern.findall(text)
        m = pattern.search(text)
        m = pattern2.findall(text2)
        s = pattern.sub('REDACTED', text)
        parts = re.split(r'\\s+', text)
        i += 1
    return parts

def matrix_multiply():
    \"\"\"Simple matrix multiplication.\"\"\"
    n = 30

    def make_matrix(n):
        return [[float(i * n + j) for j in range(n)] for i in range(n)]

    def mul(a, b, n):
        c = [[0.0] * n for _ in range(n)]
        i = 0
        while i < n:
            j = 0
            while j < n:
                s = 0.0
                k = 0
                while k < n:
                    s += a[i][k] * b[k][j]
                    k += 1
                c[i][j] = s
                j += 1
            i += 1
        return c

    a = make_matrix(n)
    b = make_matrix(n)
    loops = 0
    while loops < 50:
        c = mul(a, b, n)
        loops += 1
    return c[0][0]
"""

if __name__ == '__main__':
    runner = pyperf.Runner()
    args = add_common_args(runner)
    setup_sandbox(args.sandbox_profile, scoped=args.scoped)

    ns = make_bench_funcs(SOURCE)

    runner.bench_func('fibonacci', ns['fibonacci'])
    runner.bench_func('fibonacci_iterative', ns['fibonacci_iterative'])
    runner.bench_func('nbody', ns['nbody'])
    runner.bench_func('spectral_norm', ns['spectral_norm'])
    runner.bench_func('fannkuch', ns['fannkuch'])
    runner.bench_func('json_encode_decode', ns['json_encode_decode'])
    runner.bench_func('regex_ops', ns['regex_ops'])
    runner.bench_func('matrix_multiply', ns['matrix_multiply'])

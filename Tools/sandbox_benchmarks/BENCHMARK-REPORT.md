# Sandbox Benchmark Report

## Environment
- Platform: Linux x86_64
- Python: 3.11.14+sandbox
- CPU: x86_64
- Date: 2026-02-06 16:55
- Baseline: `sandbox-disabled`
- Compared: `sandbox-nolimits`, `sandbox-size-limits`, `sandbox-iteration`, `sandbox-dunder`, `sandbox-frozen`, `sandbox-opcodes`, `sandbox-full`

## Summary (mean overhead vs baseline)

| Category | Baseline | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| Int Arithmetic | 479.3 us | -0.7% | -0.4% | -0.9% | -1.0% | -1.3% | -1.2% | -1.1% |
| String Ops | 1.25 ms | -0.4% | +3.2% | -0.6% | -0.5% | -1.1% | -0.9% | -0.8% |
| Bytes Ops | 2.14 ms | -0.8% | +0.5% | -0.6% | -0.6% | -1.2% | -0.4% | -1.0% |
| List Ops | 7.99 ms | +0.2% | +1.9% | -0.3% | -0.7% | -0.3% | -1.0% | +0.2% |
| Dict Ops | 11.55 ms | +0.5% | +1.0% | +1.1% | +0.2% | +0.1% | +0.2% | +0.0% |
| Set Ops | 17.38 ms | -0.3% | +0.5% | +0.3% | -0.4% | -0.3% | -0.6% | -0.3% |
| Tuple Ops | 2.03 ms | +0.8% | +1.5% | +0.7% | +0.8% | +0.3% | +0.2% | +0.8% |
| Float Ops | 1.32 ms | +0.1% | +6.9% | +0.0% | +1.3% | -0.2% | -0.2% | -0.2% |
| Iteration | 6.58 ms | -0.6% | +3.5% | -0.4% | -0.5% | -0.8% | -1.0% | -0.8% |
| Function Calls | 2.90 ms | -0.4% | -0.2% | -0.1% | -0.5% | -0.5% | -0.7% | -0.9% |
| Attribute Access | 751.6 us | -0.2% | +0.2% | +0.0% | +0.0% | -0.0% | +0.1% | +0.3% |
| Class Creation | 13.14 ms | -0.6% | -0.1% | -0.4% | -0.4% | -0.6% | -0.8% | -0.8% |
| General Compute | 75.89 ms | -2.4% | -2.9% | -2.9% | -3.3% | -3.5% | -3.3% | -3.6% |
| Opcode Counting | 940.5 us | +0.3% | -0.0% | -0.0% | -0.3% | -0.9% | -0.6% | -0.7% |

## Detailed Results

### bench_attribute_access

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| dynamic_getattr | 921.2 us | 919.5 us (-0.2%) | 936.4 us (+1.6%) | 929.7 us (+0.9%) | 929.2 us (+0.9%) | 930.3 us (+1.0%) | 937.1 us (+1.7%) | 922.1 us (+0.1%) |
| dynamic_setattr | 757.1 us | 756.4 us (-0.1%) | 758.0 us (+0.1%) | 760.2 us (+0.4%) | 750.9 us (-0.8%) | 757.7 us (+0.1%) | 757.6 us (+0.1%) | 753.3 us (-0.5%) |
| getattr_dunder | 224.3 us | 223.9 us (-0.2%) | 223.3 us (-0.5%) | 223.3 us (-0.5%) | 223.8 us (-0.3%) | 224.1 us (-0.1%) | 224.2 us (-0.1%) | 223.6 us (-0.4%) |
| getattr_normal | 320.6 us | 317.0 us (-1.1%) | 316.7 us (-1.2%) | 317.4 us (-1.0%) | 317.9 us (-0.9%) | 316.5 us (-1.3%) | 318.3 us (-0.7%) | 334.5 us (+4.3%) |
| hasattr_check | 1.01 ms | 1.01 ms (~0%) | 1.02 ms (+0.3%) | 1.01 ms (-0.2%) | 1.02 ms (+0.7%) | 1.01 ms (-0.7%) | 1.01 ms (-0.5%) | 1.00 ms (-1.1%) |
| property_access | 1.84 ms | 1.84 ms (-0.3%) | 1.84 ms (-0.1%) | 1.83 ms (-0.7%) | 1.84 ms (-0.4%) | 1.83 ms (-0.7%) | 1.83 ms (-0.6%) | 1.84 ms (-0.5%) |
| setattr_normal | 544.6 us | 548.5 us (+0.7%) | 550.4 us (+1.1%) | 552.4 us (+1.4%) | 550.5 us (+1.1%) | 552.0 us (+1.4%) | 552.5 us (+1.4%) | 550.1 us (+1.0%) |
| slots_access | 385.3 us | 385.0 us (-0.1%) | 387.2 us (+0.5%) | 384.8 us (-0.1%) | 384.7 us (-0.1%) | 385.1 us (~0%) | 384.2 us (-0.3%) | 383.2 us (-0.5%) |

### bench_bytes_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| bytearray_ops | 8.27 ms | 8.23 ms (-0.6%) | 8.25 ms (-0.3%) | 8.20 ms (-0.9%) | 8.18 ms (-1.1%) | 8.16 ms (-1.3%) | 8.23 ms (-0.5%) | 8.18 ms (-1.1%) |
| bytes_concat | 178.6 us | 177.5 us (-0.6%) | 183.3 us (+2.6%) | 176.8 us (-1.0%) | 177.8 us (-0.5%) | 176.5 us (-1.2%) | 177.1 us (-0.8%) | 176.6 us (-1.1%) |
| bytes_decode | 635.6 us | 630.2 us (-0.9%) | 640.7 us (+0.8%) | 629.5 us (-1.0%) | 628.6 us (-1.1%) | 629.3 us (-1.0%) | 640.4 us (+0.7%) | 627.1 us (-1.3%) |
| bytes_from_list | 1.28 ms | 1.28 ms (-0.4%) | 1.27 ms (-0.8%) | 1.27 ms (-0.5%) | 1.29 ms (+0.4%) | 1.27 ms (-0.5%) | 1.28 ms (-0.2%) | 1.28 ms (+0.1%) |
| bytes_join | 882.2 us | 878.9 us (-0.4%) | 886.0 us (+0.4%) | 880.3 us (-0.2%) | 883.7 us (+0.2%) | 871.6 us (-1.2%) | 879.1 us (-0.3%) | 877.7 us (-0.5%) |
| bytes_split | 1.56 ms | 1.54 ms (-1.8%) | 1.57 ms (+0.2%) | 1.57 ms (+0.1%) | 1.54 ms (-1.3%) | 1.54 ms (-1.8%) | 1.55 ms (-1.2%) | 1.53 ms (-2.1%) |

### bench_class_creation

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| class_inheritance | 17.67 ms | 17.67 ms (~0%) | 17.76 ms (+0.5%) | 17.70 ms (+0.1%) | 17.73 ms (+0.3%) | 17.74 ms (+0.4%) | 17.62 ms (-0.3%) | 17.70 ms (+0.2%) |
| class_instantiation | 3.76 ms | 3.75 ms (-0.1%) | 3.72 ms (-0.8%) | 3.72 ms (-1.0%) | 3.72 ms (-1.1%) | 3.71 ms (-1.2%) | 3.71 ms (-1.3%) | 3.71 ms (-1.2%) |
| class_multiple_inheritance | 13.63 ms | 13.56 ms (-0.5%) | 13.68 ms (+0.4%) | 13.67 ms (+0.3%) | 13.69 ms (+0.5%) | 13.54 ms (-0.7%) | 13.57 ms (-0.4%) | 13.49 ms (-1.0%) |
| class_simple | 16.06 ms | 16.04 ms (-0.1%) | 16.09 ms (+0.2%) | 16.09 ms (+0.2%) | 16.09 ms (+0.2%) | 16.06 ms (~0%) | 16.01 ms (-0.3%) | 16.02 ms (-0.2%) |
| class_with_classmethod | 13.44 ms | 13.22 ms (-1.6%) | 13.38 ms (-0.4%) | 13.22 ms (-1.7%) | 13.29 ms (-1.1%) | 13.22 ms (-1.6%) | 13.22 ms (-1.6%) | 13.25 ms (-1.4%) |
| class_with_init | 16.23 ms | 16.11 ms (-0.7%) | 16.26 ms (+0.2%) | 16.20 ms (-0.2%) | 16.14 ms (-0.5%) | 16.20 ms (-0.2%) | 16.19 ms (-0.3%) | 16.08 ms (-0.9%) |
| class_with_methods | 11.20 ms | 11.10 ms (-1.0%) | 11.14 ms (-0.6%) | 11.12 ms (-0.7%) | 11.10 ms (-0.9%) | 11.12 ms (-0.8%) | 11.07 ms (-1.2%) | 11.09 ms (-1.0%) |

### bench_dict_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| dict_comprehension | 15.46 ms | 15.58 ms (+0.8%) | 15.67 ms (+1.3%) | 15.60 ms (+0.9%) | 15.58 ms (+0.8%) | 15.53 ms (+0.4%) | 15.49 ms (+0.2%) | 15.50 ms (+0.2%) |
| dict_copy | 10.58 ms | 10.30 ms (-2.6%) | 10.24 ms (-3.2%) | 10.68 ms (+1.0%) | 10.29 ms (-2.7%) | 10.39 ms (-1.8%) | 10.60 ms (+0.2%) | 10.40 ms (-1.7%) |
| dict_delete | 8.64 ms | 8.66 ms (+0.3%) | 8.72 ms (+1.0%) | 8.69 ms (+0.6%) | 8.67 ms (+0.4%) | 8.65 ms (+0.2%) | 8.63 ms (~0%) | 8.64 ms (+0.1%) |
| dict_insert | 17.68 ms | 17.78 ms (+0.6%) | 17.90 ms (+1.3%) | 17.77 ms (+0.5%) | 17.73 ms (+0.3%) | 17.72 ms (+0.2%) | 17.64 ms (-0.2%) | 17.60 ms (-0.4%) |
| dict_iterate_keys | 23.61 ms | 23.68 ms (+0.3%) | 23.91 ms (+1.3%) | 23.84 ms (+1.0%) | 23.72 ms (+0.5%) | 23.72 ms (+0.5%) | 23.63 ms (+0.1%) | 23.71 ms (+0.4%) |
| dict_lookup | 535.6 us | 542.5 us (+1.3%) | 546.5 us (+2.0%) | 539.2 us (+0.7%) | 539.7 us (+0.8%) | 537.4 us (+0.4%) | 537.3 us (+0.3%) | 539.5 us (+0.7%) |
| dict_update | 4.32 ms | 4.45 ms (+3.1%) | 4.46 ms (+3.3%) | 4.44 ms (+2.9%) | 4.39 ms (+1.6%) | 4.35 ms (+0.8%) | 4.34 ms (+0.6%) | 4.35 ms (+0.7%) |

### bench_float_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| float_arithmetic | 565.5 us | 566.0 us (+0.1%) | 567.5 us (+0.4%) | 565.8 us (+0.1%) | 577.8 us (+2.2%) | 565.6 us (~0%) | 565.4 us (~0%) | 566.4 us (+0.2%) |
| float_comparison | 559.9 us | 563.1 us (+0.6%) | 573.6 us (+2.4%) | 563.1 us (+0.6%) | 566.4 us (+1.2%) | 560.7 us (+0.1%) | 560.1 us (~0%) | 559.9 us (~0%) |
| float_conversion | 1.24 ms | 1.25 ms (+0.5%) | 1.26 ms (+1.4%) | 1.25 ms (+0.6%) | 1.25 ms (+0.6%) | 1.24 ms (-0.1%) | 1.23 ms (-0.7%) | 1.24 ms (-0.4%) |
| float_create | 993.4 us | 987.0 us (-0.6%) | 993.0 us (~0%) | 984.3 us (-0.9%) | 988.8 us (-0.5%) | 986.0 us (-0.7%) | 981.4 us (-1.2%) | 983.9 us (-1.0%) |
| float_list_ops | 3.80 ms | 3.79 ms (-0.3%) | 4.59 ms (+20.6%) | 3.80 ms (-0.2%) | 3.81 ms (+0.1%) | 3.79 ms (-0.5%) | 3.78 ms (-0.6%) | 3.79 ms (-0.4%) |
| float_math_funcs | 766.0 us | 766.3 us (~0%) | 892.7 us (+16.5%) | 765.2 us (-0.1%) | 796.9 us (+4.0%) | 765.5 us (-0.1%) | 777.3 us (+1.5%) | 766.3 us (~0%) |

### bench_function_calls

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| call_builtin | 1.06 ms | 1.05 ms (-0.7%) | 1.05 ms (-0.9%) | 1.05 ms (-0.3%) | 1.05 ms (-0.5%) | 1.05 ms (-0.5%) | 1.05 ms (-0.7%) | 1.05 ms (-0.8%) |
| call_closure | 1.37 ms | 1.36 ms (-0.4%) | 1.36 ms (-0.3%) | 1.37 ms (+0.3%) | 1.36 ms (-0.2%) | 1.37 ms (+0.2%) | 1.37 ms (+0.1%) | 1.36 ms (-0.5%) |
| call_empty | 1.09 ms | 1.08 ms (-0.5%) | 1.09 ms (+0.2%) | 1.08 ms (-0.9%) | 1.09 ms (-0.4%) | 1.08 ms (-0.6%) | 1.08 ms (-0.7%) | 1.07 ms (-1.4%) |
| call_lambda | 1.41 ms | 1.41 ms (-0.1%) | 1.41 ms (+0.1%) | 1.42 ms (+0.6%) | 1.41 ms (-0.2%) | 1.41 ms (+0.1%) | 1.41 ms (-0.2%) | 1.40 ms (-0.5%) |
| call_method | 1.36 ms | 1.36 ms (-0.1%) | 1.37 ms (+0.3%) | 1.37 ms (+0.6%) | 1.36 ms (-0.2%) | 1.36 ms (-0.5%) | 1.37 ms (~0%) | 1.36 ms (-0.4%) |
| call_recursive | 14.22 ms | 14.13 ms (-0.6%) | 14.10 ms (-0.8%) | 14.21 ms (-0.1%) | 14.10 ms (-0.8%) | 14.09 ms (-0.9%) | 14.02 ms (-1.4%) | 14.04 ms (-1.2%) |
| call_with_args | 2.08 ms | 2.07 ms (-0.4%) | 2.08 ms (-0.2%) | 2.06 ms (-0.8%) | 2.06 ms (-1.1%) | 2.07 ms (-0.6%) | 2.06 ms (-1.2%) | 2.05 ms (-1.4%) |
| call_with_kwargs | 1.67 ms | 1.67 ms (-0.1%) | 1.66 ms (-0.7%) | 1.67 ms (-0.1%) | 1.67 ms (-0.1%) | 1.66 ms (-0.7%) | 1.66 ms (-0.8%) | 1.66 ms (-0.7%) |
| call_with_mixed | 1.86 ms | 1.84 ms (-1.0%) | 1.87 ms (+0.6%) | 1.86 ms (+0.1%) | 1.84 ms (-1.0%) | 1.84 ms (-1.4%) | 1.84 ms (-1.1%) | 1.85 ms (-0.9%) |

### bench_general_compute

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| fannkuch | 193.18 ms | 190.75 ms (-1.3%) | 192.43 ms (-0.4%) | 190.50 ms (-1.4%) | 191.21 ms (-1.0%) | 190.70 ms (-1.3%) | 190.36 ms (-1.5%) | 189.89 ms (-1.7%) |
| fibonacci | 4.88 ms | 4.82 ms (-1.2%) | 4.84 ms (-0.8%) | 4.82 ms (-1.2%) | 4.82 ms (-1.3%) | 4.81 ms (-1.5%) | 4.81 ms (-1.5%) | 4.80 ms (-1.6%) |
| fibonacci_iterative | 3.14 ms | 3.11 ms (-1.1%) | 3.13 ms (-0.5%) | 3.11 ms (-0.9%) | 3.12 ms (-0.8%) | 3.12 ms (-0.8%) | 3.12 ms (-0.8%) | 3.12 ms (-0.7%) |
| json_encode_decode | 24.98 ms | 25.05 ms (+0.3%) | 24.74 ms (-1.0%) | 24.92 ms (-0.2%) | 24.79 ms (-0.7%) | 24.56 ms (-1.7%) | 24.71 ms (-1.1%) | 24.67 ms (-1.2%) |
| matrix_multiply | 53.23 ms | 55.44 ms (+4.1%) | 53.11 ms (-0.2%) | 53.53 ms (+0.6%) | 52.71 ms (-1.0%) | 52.72 ms (-1.0%) | 52.67 ms (-1.1%) | 52.57 ms (-1.2%) |
| nbody | 30.49 ms | 24.29 ms (-20.3%) | 24.50 ms (-19.7%) | 24.42 ms (-19.9%) | 24.22 ms (-20.6%) | 24.22 ms (-20.6%) | 24.70 ms (-19.0%) | 24.31 ms (-20.3%) |
| regex_ops | 8.60 ms | 8.60 ms (~0%) | 8.53 ms (-0.8%) | 8.56 ms (-0.4%) | 8.53 ms (-0.8%) | 8.55 ms (-0.5%) | 8.53 ms (-0.8%) | 8.51 ms (-1.0%) |
| spectral_norm | 288.60 ms | 289.16 ms (+0.2%) | 289.44 ms (+0.3%) | 288.39 ms (-0.1%) | 287.39 ms (-0.4%) | 286.75 ms (-0.6%) | 287.44 ms (-0.4%) | 286.07 ms (-0.9%) |

### bench_int_arithmetic

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| int_add_medium | 382.6 us | 384.4 us (+0.5%) | 380.3 us (-0.6%) | 377.8 us (-1.2%) | 379.4 us (-0.8%) | 379.2 us (-0.9%) | 381.8 us (-0.2%) | 381.4 us (-0.3%) |
| int_add_small | 737.1 us | 740.1 us (+0.4%) | 733.9 us (-0.4%) | 733.3 us (-0.5%) | 733.2 us (-0.5%) | 730.9 us (-0.8%) | 731.0 us (-0.8%) | 729.3 us (-1.1%) |
| int_divmod | 953.1 us | 932.4 us (-2.2%) | 948.5 us (-0.5%) | 943.6 us (-1.0%) | 934.7 us (-1.9%) | 933.9 us (-2.0%) | 935.4 us (-1.9%) | 938.1 us (-1.6%) |
| int_mul_medium | 107.9 us | 106.4 us (-1.4%) | 106.3 us (-1.5%) | 106.0 us (-1.7%) | 106.2 us (-1.6%) | 105.0 us (-2.7%) | 105.5 us (-2.2%) | 106.3 us (-1.5%) |
| int_mul_small | 485.1 us | 481.1 us (-0.8%) | 486.8 us (+0.3%) | 484.0 us (-0.2%) | 480.5 us (-1.0%) | 482.0 us (-0.6%) | 478.5 us (-1.4%) | 479.2 us (-1.2%) |
| int_pow_small | 210.3 us | 208.2 us (-1.0%) | 210.2 us (~0%) | 208.5 us (-0.9%) | 209.6 us (-0.3%) | 208.3 us (-0.9%) | 209.2 us (-0.5%) | 208.0 us (-1.1%) |

### bench_iteration

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| iter_dict_comprehension | 7.82 ms | 7.78 ms (-0.5%) | 7.80 ms (-0.3%) | 7.82 ms (~0%) | 7.76 ms (-0.9%) | 7.76 ms (-0.8%) | 7.77 ms (-0.7%) | 7.79 ms (-0.5%) |
| iter_enumerate | 5.56 ms | 5.50 ms (-0.9%) | 5.61 ms (+0.9%) | 5.54 ms (-0.3%) | 5.55 ms (-0.1%) | 5.51 ms (-0.9%) | 5.50 ms (-1.0%) | 5.53 ms (-0.4%) |
| iter_filter | 8.74 ms | 8.70 ms (-0.5%) | 8.73 ms (-0.1%) | 8.69 ms (-0.5%) | 8.69 ms (-0.5%) | 8.66 ms (-0.9%) | 8.70 ms (-0.5%) | 8.66 ms (-0.9%) |
| iter_for_list | 2.45 ms | 2.42 ms (-1.1%) | 2.47 ms (+0.7%) | 2.41 ms (-1.5%) | 2.42 ms (-1.1%) | 2.42 ms (-1.1%) | 2.41 ms (-1.7%) | 2.41 ms (-1.4%) |
| iter_for_range | 3.04 ms | 3.00 ms (-1.2%) | 4.15 ms (+36.5%) | 3.05 ms (+0.3%) | 3.05 ms (+0.3%) | 3.03 ms (-0.3%) | 2.99 ms (-1.5%) | 3.03 ms (-0.2%) |
| iter_generator | 7.24 ms | 7.18 ms (-0.8%) | 7.24 ms (~0%) | 7.18 ms (-0.8%) | 7.20 ms (-0.5%) | 7.18 ms (-0.8%) | 7.16 ms (-1.0%) | 7.15 ms (-1.3%) |
| iter_list_comprehension | 10.86 ms | 10.90 ms (+0.4%) | 10.82 ms (-0.3%) | 10.87 ms (+0.1%) | 10.82 ms (-0.3%) | 10.84 ms (-0.1%) | 10.82 ms (-0.4%) | 10.79 ms (-0.6%) |
| iter_map | 7.04 ms | 7.01 ms (-0.4%) | 7.05 ms (+0.2%) | 7.01 ms (-0.4%) | 7.05 ms (+0.2%) | 7.00 ms (-0.5%) | 7.01 ms (-0.4%) | 6.99 ms (-0.7%) |
| iter_nested | 8.14 ms | 8.07 ms (-0.8%) | 8.00 ms (-1.7%) | 8.01 ms (-1.5%) | 8.00 ms (-1.7%) | 8.00 ms (-1.7%) | 8.00 ms (-1.7%) | 8.04 ms (-1.2%) |
| iter_zip | 4.88 ms | 4.87 ms (-0.3%) | 4.85 ms (-0.6%) | 4.89 ms (+0.2%) | 4.86 ms (-0.5%) | 4.84 ms (-1.0%) | 4.83 ms (-1.0%) | 4.86 ms (-0.4%) |

### bench_list_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| list_append | 12.97 ms | 13.48 ms (+3.9%) | 13.08 ms (+0.8%) | 13.01 ms (+0.3%) | 12.95 ms (-0.2%) | 12.93 ms (-0.4%) | 12.94 ms (-0.2%) | 12.94 ms (-0.2%) |
| list_comprehension | 10.43 ms | 10.41 ms (-0.2%) | 10.49 ms (+0.6%) | 10.38 ms (-0.5%) | 10.41 ms (-0.2%) | 10.44 ms (+0.1%) | 10.40 ms (-0.3%) | 10.43 ms (~0%) |
| list_copy | 14.16 ms | 14.33 ms (+1.2%) | 14.75 ms (+4.2%) | 14.14 ms (-0.2%) | 14.20 ms (+0.3%) | 14.68 ms (+3.7%) | 13.89 ms (-1.9%) | 14.42 ms (+1.8%) |
| list_extend | 703.0 us | 682.3 us (-2.9%) | 696.1 us (-1.0%) | 691.4 us (-1.6%) | 687.2 us (-2.2%) | 683.7 us (-2.7%) | 676.5 us (-3.8%) | 712.3 us (+1.3%) |
| list_index_access | 584.9 us | 582.7 us (-0.4%) | 628.0 us (+7.4%) | 578.2 us (-1.1%) | 571.3 us (-2.3%) | 573.9 us (-1.9%) | 581.6 us (-0.6%) | 577.9 us (-1.2%) |
| list_pop | 4.29 ms | 4.31 ms (+0.4%) | 4.36 ms (+1.5%) | 4.32 ms (+0.6%) | 4.30 ms (~0%) | 4.31 ms (+0.3%) | 4.29 ms (~0%) | 4.28 ms (-0.2%) |
| list_sort | 12.76 ms | 12.67 ms (-0.8%) | 12.71 ms (-0.4%) | 12.87 ms (+0.8%) | 12.69 ms (-0.6%) | 12.57 ms (-1.5%) | 12.73 ms (-0.2%) | 12.71 ms (-0.4%) |

### bench_opcount_overhead

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| arithmetic_heavy_counted | 1.28 ms | 1.28 ms (+0.4%) | 1.28 ms (~0%) | 1.28 ms (+0.2%) | 1.27 ms (-0.8%) | 1.27 ms (-0.4%) | 1.26 ms (-0.8%) | 1.27 ms (-0.2%) |
| arithmetic_heavy_normal | 1.08 ms | 1.09 ms (+0.9%) | 1.08 ms (+0.3%) | 1.08 ms (+0.3%) | 1.08 ms (+0.5%) | 1.07 ms (-0.9%) | 1.07 ms (-0.4%) | 1.07 ms (-0.9%) |
| function_call_heavy_counted | 817.6 us | 825.6 us (+1.0%) | 815.9 us (-0.2%) | 813.9 us (-0.5%) | 814.6 us (-0.4%) | 809.0 us (-1.1%) | 814.0 us (-0.4%) | 814.7 us (-0.4%) |
| function_call_heavy_normal | 668.5 us | 665.0 us (-0.5%) | 666.4 us (-0.3%) | 666.3 us (-0.3%) | 664.0 us (-0.7%) | 661.4 us (-1.1%) | 662.3 us (-0.9%) | 661.7 us (-1.0%) |
| mixed_operations_counted | 330.1 us | 331.9 us (+0.6%) | 331.2 us (+0.3%) | 330.6 us (+0.2%) | 330.4 us (+0.1%) | 329.7 us (-0.1%) | 328.4 us (-0.5%) | 329.3 us (-0.2%) |
| mixed_operations_normal | 282.2 us | 281.3 us (-0.4%) | 282.4 us (~0%) | 281.2 us (-0.4%) | 280.6 us (-0.6%) | 279.0 us (-1.1%) | 281.4 us (-0.3%) | 280.0 us (-0.8%) |
| tight_loop_counted | 1.66 ms | 1.67 ms (+0.5%) | 1.66 ms (+0.1%) | 1.66 ms (-0.1%) | 1.65 ms (-0.7%) | 1.64 ms (-1.2%) | 1.64 ms (-0.9%) | 1.64 ms (-1.2%) |
| tight_loop_normal | 1.42 ms | 1.42 ms (+0.1%) | 1.41 ms (-0.5%) | 1.42 ms (+0.3%) | 1.41 ms (-0.3%) | 1.40 ms (-1.2%) | 1.41 ms (-0.1%) | 1.41 ms (-0.6%) |

### bench_set_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| set_add | 16.11 ms | 16.19 ms (+0.5%) | 16.35 ms (+1.5%) | 16.20 ms (+0.5%) | 16.23 ms (+0.7%) | 16.22 ms (+0.7%) | 16.13 ms (+0.1%) | 16.16 ms (+0.3%) |
| set_comprehension | 12.98 ms | 12.94 ms (-0.3%) | 13.04 ms (+0.4%) | 12.96 ms (-0.2%) | 12.98 ms (~0%) | 12.96 ms (-0.1%) | 12.90 ms (-0.6%) | 12.94 ms (-0.3%) |
| set_contains | 844.0 us | 840.7 us (-0.4%) | 847.5 us (+0.4%) | 839.6 us (-0.5%) | 840.2 us (-0.5%) | 837.0 us (-0.8%) | 838.8 us (-0.6%) | 836.1 us (-0.9%) |
| set_difference | 21.44 ms | 21.39 ms (-0.2%) | 21.54 ms (+0.5%) | 21.37 ms (-0.3%) | 21.37 ms (-0.3%) | 21.33 ms (-0.5%) | 21.49 ms (+0.2%) | 21.74 ms (+1.4%) |
| set_intersection | 21.73 ms | 21.73 ms (~0%) | 21.91 ms (+0.8%) | 22.37 ms (+2.9%) | 21.73 ms (~0%) | 21.68 ms (-0.2%) | 21.68 ms (-0.2%) | 21.66 ms (-0.3%) |
| set_union | 31.19 ms | 30.83 ms (-1.2%) | 30.99 ms (-0.7%) | 30.99 ms (-0.7%) | 30.45 ms (-2.4%) | 30.95 ms (-0.8%) | 30.35 ms (-2.7%) | 30.64 ms (-1.8%) |

### bench_str_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| str_concat | 177.9 us | 175.7 us (-1.2%) | 176.9 us (-0.6%) | 176.7 us (-0.7%) | 175.8 us (-1.2%) | 175.1 us (-1.6%) | 175.8 us (-1.2%) | 176.1 us (-1.0%) |
| str_encode | 764.6 us | 764.2 us (~0%) | 772.1 us (+1.0%) | 765.5 us (+0.1%) | 768.0 us (+0.4%) | 760.0 us (-0.6%) | 760.1 us (-0.6%) | 761.7 us (-0.4%) |
| str_format | 1.68 ms | 1.69 ms (+0.1%) | 1.68 ms (~0%) | 1.67 ms (-0.7%) | 1.67 ms (-0.6%) | 1.67 ms (-0.5%) | 1.67 ms (-0.9%) | 1.67 ms (-0.9%) |
| str_join | 1.09 ms | 1.08 ms (-0.5%) | 1.08 ms (-0.7%) | 1.08 ms (-1.0%) | 1.08 ms (-1.0%) | 1.07 ms (-1.6%) | 1.08 ms (-0.7%) | 1.07 ms (-1.2%) |
| str_replace | 1.09 ms | 1.09 ms (+0.1%) | 1.10 ms (+0.6%) | 1.08 ms (-0.8%) | 1.08 ms (-0.6%) | 1.08 ms (-0.9%) | 1.08 ms (-0.5%) | 1.08 ms (-0.8%) |
| str_split | 1.74 ms | 1.74 ms (+0.1%) | 1.74 ms (-0.2%) | 1.73 ms (-0.5%) | 1.75 ms (+0.4%) | 1.72 ms (-1.1%) | 1.73 ms (-0.5%) | 1.74 ms (~0%) |
| str_startswith | 2.21 ms | 2.19 ms (-1.1%) | 2.70 ms (+22.0%) | 2.21 ms (-0.3%) | 2.20 ms (-0.7%) | 2.18 ms (-1.6%) | 2.17 ms (-1.7%) | 2.19 ms (-1.3%) |

### bench_tuple_ops

| Benchmark | sandbox-disabled | sandbox-nolimits | sandbox-size-limits | sandbox-iteration | sandbox-dunder | sandbox-frozen | sandbox-opcodes | sandbox-full |
|---|---|---|---|---|---|---|---|---|
| tuple_concat | 830.9 us | 830.6 us (~0%) | 851.6 us (+2.5%) | 829.6 us (-0.2%) | 833.3 us (+0.3%) | 828.4 us (-0.3%) | 825.7 us (-0.6%) | 830.0 us (-0.1%) |
| tuple_contains | 5.39 ms | 5.48 ms (+1.6%) | 5.48 ms (+1.7%) | 5.44 ms (+1.0%) | 5.47 ms (+1.6%) | 5.41 ms (+0.5%) | 5.44 ms (+1.0%) | 5.45 ms (+1.2%) |
| tuple_create | 1.88 ms | 1.87 ms (-0.1%) | 1.88 ms (+0.4%) | 1.86 ms (-0.7%) | 1.87 ms (-0.4%) | 1.87 ms (-0.5%) | 1.86 ms (-0.9%) | 1.87 ms (-0.3%) |
| tuple_index_access | 756.8 us | 764.5 us (+1.0%) | 769.1 us (+1.6%) | 759.2 us (+0.3%) | 764.7 us (+1.0%) | 759.4 us (+0.3%) | 762.5 us (+0.8%) | 758.8 us (+0.3%) |
| tuple_slice | 1.37 ms | 1.39 ms (+1.0%) | 1.39 ms (+1.7%) | 1.39 ms (+1.5%) | 1.39 ms (+1.7%) | 1.39 ms (+1.1%) | 1.38 ms (+0.5%) | 1.38 ms (+0.9%) |
| tuple_unpack | 1.95 ms | 1.97 ms (+1.2%) | 1.97 ms (+1.3%) | 1.99 ms (+2.3%) | 1.96 ms (+0.6%) | 1.97 ms (+0.8%) | 1.95 ms (+0.2%) | 2.01 ms (+2.9%) |

## Notes

- Overhead percentages are computed as: (compare_mean - baseline_mean) / baseline_mean * 100
- Summary shows the average overhead across all sub-benchmarks in each category
- Times are mean values reported by pyperf

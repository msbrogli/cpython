# Test: constant folding - nested
# (1 + 2) * (3 + 4) should fold to 21 with operations_count=3
x = (1 + 2) * (3 + 4)

# Test: walrus operator (named expression)
# NamedExpr counts as operation
if (n := len([1, 2, 3])) > 0:
    pass

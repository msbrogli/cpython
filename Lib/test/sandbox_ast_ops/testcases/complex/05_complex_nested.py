# Test: complex nested structure
# Multiple nested expressions and statements
def complex_func(x, y):
    if x > 0:
        if y > 0:
            return x + y
        else:
            return x - y
    elif x < 0:
        result = 0
        for i in range(abs(x)):
            result = result + i
        return result
    else:
        return 0

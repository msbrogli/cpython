# Test: decorator usage
# Decorator definition and application
def decorator(func):
    def wrapper(*args):
        return func(*args)
    return wrapper

@decorator
def foo(x):
    return x * 2

foo(5)

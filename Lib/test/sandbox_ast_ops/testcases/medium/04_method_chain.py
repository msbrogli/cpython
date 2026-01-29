# Test: method call chain
# Attribute access + Call combinations
class Foo:
    def bar(self):
        return self

Foo().bar().bar()

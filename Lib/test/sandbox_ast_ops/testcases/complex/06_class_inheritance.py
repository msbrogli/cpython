# Test: class with methods and inheritance
# Complex class definition with multiple operations
class Base:
    def method(self):
        return 42

class Derived(Base):
    def __init__(self):
        self.value = 0

    def compute(self, x):
        return self.value + x

d = Derived()
d.compute(10)

"""Tests for object creation hook functionality."""

import sys
import unittest


class ObjectCreationHookTests(unittest.TestCase):
    """Test object creation hook functionality."""

    def setUp(self):
        self.original_hook = sys.sandbox.creation_hook

    def tearDown(self):
        sys.sandbox.creation_hook = self.original_hook

    def test_getobjectcreationhook_default_none(self):
        """Default hook should be None."""
        sys.sandbox.creation_hook = None
        self.assertIsNone(sys.sandbox.creation_hook)

    def test_setobjectcreationhook_requires_callable(self):
        """setobjectcreationhook should require a callable."""
        with self.assertRaises(TypeError):
            sys.sandbox.creation_hook = "not callable"

    def test_setobjectcreationhook_accepts_none(self):
        """setobjectcreationhook should accept None."""
        sys.sandbox.creation_hook = None
        self.assertIsNone(sys.sandbox.creation_hook)

    def test_hook_called_on_object_creation(self):
        """Hook should be called when creating objects."""
        created_objects = []

        def hook(obj, type_, frame, context):
            created_objects.append((type_.__name__, context))
            return obj

        sys.sandbox.creation_hook = hook

        class MyClass:
            pass

        instance = MyClass()

        # Check that our class creation was captured
        found = any(name == 'MyClass' for name, _ in created_objects)
        self.assertTrue(found, f"Expected MyClass in {created_objects}")

    def test_hook_can_block_creation(self):
        """Hook can raise exception to block object creation."""
        def blocking_hook(obj, type_, frame, context):
            if type_.__name__ == 'BlockedClass':
                raise ValueError("Creation blocked by hook")
            return obj

        sys.sandbox.creation_hook = blocking_hook

        class BlockedClass:
            pass

        with self.assertRaises(ValueError) as cm:
            instance = BlockedClass()
        self.assertIn("blocked by hook", str(cm.exception))

    def test_hook_returning_same_object(self):
        """Hook returning the same object should not cause use-after-free."""
        call_count = [0]

        def identity_hook(obj, type_, frame, context):
            call_count[0] += 1
            # Return the same object - this should NOT decref it
            return obj

        sys.sandbox.creation_hook = identity_hook

        class TestClass:
            pass

        # Create multiple instances to stress test
        instances = []
        for i in range(10):
            inst = TestClass()
            instances.append(inst)
            # Verify the object is still valid
            self.assertIsInstance(inst, TestClass)

        # All instances should still be valid
        self.assertEqual(len(instances), 10)
        for inst in instances:
            self.assertIsInstance(inst, TestClass)

        # Hook should have been called
        self.assertGreater(call_count[0], 0)

    def test_hook_replacing_with_different_object(self):
        """Hook returning a different object should work correctly."""
        class Replacement:
            pass

        def replacing_hook(obj, type_, frame, context):
            if type_.__name__ == 'Original':
                return Replacement()
            return obj

        sys.sandbox.creation_hook = replacing_hook

        class Original:
            pass

        # Creating Original should return Replacement
        result = Original()
        self.assertIsInstance(result, Replacement)


if __name__ == '__main__':
    unittest.main()

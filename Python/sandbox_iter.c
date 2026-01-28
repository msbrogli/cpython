/* Sandbox iterator wrapper
 *
 * This file contains the sandbox iterator wrapper type which wraps iterators
 * to check iteration limits on each step.
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* Declared in sandbox_core.c */
extern int _sandbox_wrapper_type_ready;
extern int _PySandbox_InitWrapperType(void);

/* ============ Sandbox Iterator Wrapper ============ */

/* Sandbox iterator wrapper - wraps any iterator to check limits on each step.
 *
 * This provides protection against infinite iteration attacks for ALL call
 * sites that use PyObject_GetIter(), including:
 * - list(), tuple(), set(), frozenset()
 * - all(), any(), zip(), map(), filter(), enumerate()
 * - for loops (via GET_ITER opcode)
 * - sum(), min(), max(), sorted()
 * - deque.extend(), etc.
 *
 * By wrapping at the single point where iterators are created (PyObject_GetIter),
 * we automatically protect all 26+ direct tp_iternext call sites.
 */
typedef struct {
    PyObject_HEAD
    PyObject *wrapped;  /* The wrapped iterator (strong ref) */
} _PySandboxIteratorWrapper;

static void
sandbox_iter_wrapper_dealloc(_PySandboxIteratorWrapper *self)
{
    PyObject_GC_UnTrack(self);
    Py_XDECREF(self->wrapped);
    PyObject_GC_Del(self);
}

static int
sandbox_iter_wrapper_traverse(_PySandboxIteratorWrapper *self, visitproc visit, void *arg)
{
    Py_VISIT(self->wrapped);
    return 0;
}

static int
sandbox_iter_wrapper_clear(_PySandboxIteratorWrapper *self)
{
    Py_CLEAR(self->wrapped);
    return 0;
}

static PyObject *
sandbox_iter_wrapper_iter(PyObject *self)
{
    Py_INCREF(self);
    return self;
}

static PyObject *
sandbox_iter_wrapper_iternext(_PySandboxIteratorWrapper *self)
{
    /* Check iteration limits BEFORE delegating (inlined for zero overhead) */
    if (sandbox_check_iteration() < 0) {
        return NULL;  /* Exception already set */
    }

    /* Delegate to wrapped iterator's tp_iternext */
    if (self->wrapped == NULL) {
        PyErr_SetString(PyExc_RuntimeError,
                        "sandbox iterator wrapper has no wrapped iterator");
        return NULL;
    }

    PyTypeObject *type = Py_TYPE(self->wrapped);
    if (type->tp_iternext == NULL) {
        PyErr_SetString(PyExc_TypeError,
                        "wrapped object is not an iterator");
        return NULL;
    }

    return (*type->tp_iternext)(self->wrapped);
}

PyTypeObject _PySandboxIteratorWrapper_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "_sandbox_iterator_wrapper",
    .tp_basicsize = sizeof(_PySandboxIteratorWrapper),
    .tp_dealloc = (destructor)sandbox_iter_wrapper_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .tp_traverse = (traverseproc)sandbox_iter_wrapper_traverse,
    .tp_clear = (inquiry)sandbox_iter_wrapper_clear,
    .tp_iter = sandbox_iter_wrapper_iter,
    .tp_iternext = (iternextfunc)sandbox_iter_wrapper_iternext,
};

/* ============ Wrap Iterator Function ============ */

/* _PySandbox_WrapIterator - Wrap an iterator if sandbox scope is active.
 *
 * This function should be called on every iterator returned by PyObject_GetIter().
 * If the current execution is within a sandbox scope (a registered filename),
 * the iterator is wrapped to check iteration limits on each step.
 *
 * Parameters:
 *   iter: The iterator to potentially wrap (borrowed reference)
 *
 * Returns:
 *   - New reference to a wrapper iterator (if in sandbox scope)
 *   - New reference to the original iterator (if not in scope)
 *   - NULL on error (exception set)
 *
 * Note: The caller is responsible for decref'ing the original iterator
 * AFTER calling this function if it was returned from tp_iter.
 */
PyObject *
_PySandbox_WrapIterator(PyObject *iter)
{
    if (iter == NULL) {
        return NULL;
    }

    /* Safety check for early interpreter initialization.
     * During interpreter bootstrapping (freeze phase, etc.), thread state
     * may not be available. In this case, don't wrap. */
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        Py_INCREF(iter);
        return iter;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        Py_INCREF(iter);
        return iter;
    }

    /* Check if we should wrap: sandbox scope must be active.
     * Inline the scope check to avoid redundant interp lookup. */
    _PySandboxState *sandbox = &interp->sandbox;
    if (sandbox->registered_filenames == NULL) {
        Py_INCREF(iter);
        return iter;  /* No filenames registered, not in scope */
    }
    _PyInterpreterFrame *frame = get_current_iframe(tstate);
    if (frame == NULL || !frame_in_sandbox_scope(sandbox->registered_filenames, frame)) {
        Py_INCREF(iter);
        return iter;  /* No wrapping needed */
    }

    /* Initialize wrapper type lazily on first use.
     * This is done here instead of in _PySandbox_Init because we now
     * have a valid thread state. */
    if (!_sandbox_wrapper_type_ready) {
        if (_PySandbox_InitWrapperType() < 0) {
            /* Type initialization failed - don't wrap, just return original */
            PyErr_Clear();
            Py_INCREF(iter);
            return iter;
        }
    }

    /* Avoid wrapping an already-wrapped iterator */
    if (Py_TYPE(iter) == &_PySandboxIteratorWrapper_Type) {
        Py_INCREF(iter);
        return iter;
    }

    /* Create wrapper */
    _PySandboxIteratorWrapper *wrapper = PyObject_GC_New(
        _PySandboxIteratorWrapper, &_PySandboxIteratorWrapper_Type);
    if (wrapper == NULL) {
        return NULL;
    }

    Py_INCREF(iter);
    wrapper->wrapped = iter;
    PyObject_GC_Track(wrapper);

    return (PyObject *)wrapper;
}

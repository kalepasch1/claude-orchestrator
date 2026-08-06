"""pareto package.

The 2080 stack lives in `pareto/2080/`, but `2080` is not a valid Python
identifier, so `pareto.2080.household_legal` cannot be written as an import.
Extending __path__ over that directory makes the subpackages reachable as
`pareto.household_legal`, `pareto.contracts`, ... without moving a single file
or breaking the existing sys.path-based imports inside them.

__path__ is bound explicitly from globals() rather than mutated in place: a bare
`__path__.append(...)` reads a name a static checker cannot see defined here.
"""
import os as _os

__path__ = list(globals().get("__path__", []))

_stack = _os.path.join(_os.path.dirname(__file__), "2080")
if _os.path.isdir(_stack) and _stack not in __path__:
    # Appended, never prepended, so anything defined directly under pareto/
    # keeps precedence over the 2080 subtree.
    __path__.append(_stack)

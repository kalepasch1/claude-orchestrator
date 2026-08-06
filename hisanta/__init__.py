"""hisanta package root.

The domain subpackages (gifting, grandma, kindness, mastery, school) live one
directory deeper, in hisanta/hisanta/, while `contracts` and `tests` sit at this
level. Under pytest the rootdir is the repo, so `hisanta` binds to THIS
directory — which meant `import hisanta.mastery.engine` and
`import hisanta.grandma.rail` raised ModuleNotFoundError even though the code was
right there, and their whole test suites failed at collection.

Extending __path__ makes both levels one package. This directory stays FIRST, so
`hisanta.contracts` keeps resolving to the canonical hisanta/contracts/family.py
rather than the parallel copy beneath it.
"""
import os as _os

__path__.append(_os.path.join(_os.path.dirname(__file__), "hisanta"))

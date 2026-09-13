"""Marks the integration suite as a package.

Without it, pytest's prepend import mode puts `tests/integration/` itself on `sys.path`,
where this package's `conftest.py` would shadow `tests/conftest.py` for the pure suite's
`from conftest import StubCatalog`.
"""

"""Load an extension-less script (scripts/e2e, scripts/eval) as a module for tests."""

import importlib.machinery
import importlib.util


def load_script(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module

"""The layer rules of the package, checked on every import statement.

core  <-  models  <-  views  <-  controllers  <-  cli / mcp

A layer may import from the layers to its left only. The single exception
is :meth:`indtrader.core.context.AppContext.create`, the composition root,
which builds the market-data model.
"""

import ast
import os
import unittest

from _base import ROOT

PACKAGE = os.path.join(ROOT, "indtrader")
FORBIDDEN = {
    "core": ("indtrader.models", "indtrader.views", "indtrader.controllers", "indtrader.cli", "indtrader.mcp"),
    "models": ("indtrader.views", "indtrader.controllers", "indtrader.cli", "indtrader.mcp"),
    "views": ("indtrader.controllers", "indtrader.cli", "indtrader.mcp"),
    "controllers": ("indtrader.cli", "indtrader.mcp"),
}
ALLOWED = {("core/context.py", "indtrader.models.data.market_data")}


def imports_of(path):
    with open(path, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name


class TestLayers(unittest.TestCase):
    def test_no_import_points_up(self):
        broken = []
        for layer, banned in FORBIDDEN.items():
            for folder, _, files in os.walk(os.path.join(PACKAGE, layer)):
                for name in files:
                    if not name.endswith(".py"):
                        continue
                    path = os.path.join(folder, name)
                    relative = os.path.relpath(path, PACKAGE).replace(os.sep, "/")
                    for module in imports_of(path):
                        if module.startswith(banned) and (relative, module) not in ALLOWED:
                            broken.append("%s imports %s" % (relative, module))
        self.assertEqual(broken, [])

    def test_models_do_not_print(self):
        printing = []
        for folder, _, files in os.walk(os.path.join(PACKAGE, "models")):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as fh:
                        tree = ast.parse(fh.read())
                    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "print"]
                    if calls:
                        printing.append(os.path.relpath(path, PACKAGE))
        self.assertEqual(printing, [])

    def test_every_agent_has_a_report_view(self):
        from indtrader.models.agents import REGISTRY
        from indtrader.views.reports import REPORTS
        self.assertEqual(sorted(REGISTRY), sorted(REPORTS))


if __name__ == "__main__":
    unittest.main()

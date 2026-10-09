"""Every whitelisted endpoint carries its cross-cutting decorator.

`ast`-only: it never imports portal_api or hr_api (both import frappe).
"""

import ast
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parent.parent


def _decorator_name(node):
	target = node.func if isinstance(node, ast.Call) else node
	if isinstance(target, ast.Attribute):
		return target.attr
	if isinstance(target, ast.Name):
		return target.id
	return None


def _public_functions(filename):
	path = _DIR / filename
	if not path.exists():
		return None
	tree = ast.parse(path.read_text())
	return [
		n
		for n in tree.body
		if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and not n.name.startswith("_")
	]


class DecoratorsPresent(unittest.TestCase):
	def _check(self, filename, *decorators):
		functions = _public_functions(filename)
		if functions is None:
			self.skipTest(f"{filename} does not exist yet")
		for fn in functions:
			names = {_decorator_name(d) for d in fn.decorator_list}
			self.assertTrue(names & set(decorators), f"{filename}: {fn.name} is missing @{decorators[0]}")

	def test_portal_api_functions_are_portal_guest(self):
		self._check("portal_api.py", "portal_guest")

	def test_hr_api_functions_are_hr_action(self):
		# A read that must work while the Settings are incomplete checks the role only.
		self._check("hr_api.py", "hr_action", "hr_read")


if __name__ == "__main__":
	unittest.main()

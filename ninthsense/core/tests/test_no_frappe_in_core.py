"""core/ never imports frappe. `ast`-only: it never imports what it inspects."""

import ast
import unittest
from pathlib import Path

_CORE_DIR = Path(__file__).resolve().parent.parent


class NoFrappeInCore(unittest.TestCase):
	def test_no_module_in_core_imports_frappe(self):
		files = [p for p in _CORE_DIR.rglob("*.py") if "__pycache__" not in p.parts]
		self.assertTrue(files)
		for path in files:
			for node in ast.walk(ast.parse(path.read_text())):
				if isinstance(node, ast.Import):
					names = [a.name for a in node.names]
				elif isinstance(node, ast.ImportFrom):
					names = [node.module or ""]
				else:
					continue
				for name in names:
					self.assertNotEqual(name.split(".")[0], "frappe", f"{path.name} imports frappe")


if __name__ == "__main__":
	unittest.main()

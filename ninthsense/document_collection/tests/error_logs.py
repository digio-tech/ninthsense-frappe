"""Error Log is a MyISAM table in Frappe, so a test's rollback never removes its rows."""

import frappe
from frappe.tests.utils import FrappeTestCase


class AppTestCase(FrappeTestCase):
	"""A FrappeTestCase that removes the Error Log rows written while its class ran."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls._error_logs_before = set(frappe.get_all("Error Log", pluck="name"))

	@classmethod
	def tearDownClass(cls):
		written = set(frappe.get_all("Error Log", pluck="name")) - cls._error_logs_before
		if written:
			frappe.db.delete("Error Log", {"name": ("in", sorted(written))})
		super().tearDownClass()

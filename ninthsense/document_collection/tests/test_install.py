"""US4: what install creates, that it is idempotent, and that it creates nothing company-specific (T068)."""

import frappe

from ninthsense import install
from ninthsense.document_collection.tests.error_logs import AppTestCase

SETTINGS = "Document Collection Settings"
TEMPLATE = "Document Collection Template"
COMPANY_DOCTYPES = ("Department", "Designation", "Branch", "Letter Head", "Holiday List")


class TestInstall(AppTestCase):
	def test_install_creates_the_seeded_records(self):
		self.assertEqual(
			frappe.db.count(
				"Employee Document Type", {"document_code": ["in", [d[4] for d in install.DOCUMENT_TYPES]]}
			),
			14,
		)
		self.assertTrue(frappe.db.exists("Email Template", install.EMAIL_TEMPLATE))
		self.assertEqual(frappe.get_all(TEMPLATE, pluck="name"), [install.DEFAULT_TEMPLATE])
		self.assertEqual(len(frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE).documents), 8)
		self.assertFalse(frappe.get_single(SETTINGS).portal_url)
		self.assertFalse(frappe.get_meta(SETTINGS).has_field("onboarding_documents"))

	# US4 AS-4: HR's edits to the seeded template survive a re-run.
	def test_running_again_changes_nothing_and_keeps_hrs_edits(self):
		template = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		original = [r.document_type for r in template.documents]
		dropped = template.documents[-1]
		template.field_mapping = [
			r for r in template.field_mapping if r.source_document != dropped.document_type
		]
		for row in template.field_mapping:
			if row.fallback_document == dropped.document_type:
				row.fallback_document = None
		template.remove(dropped)
		template.documents[-1].is_mandatory = 1
		template.save(ignore_permissions=True)

		counts = self.company_counts()
		types = frappe.db.count("Employee Document Type")
		install.after_install()

		template.reload()
		self.assertEqual([r.document_type for r in template.documents], original[:-1])
		self.assertEqual(template.documents[-1].is_mandatory, 1)
		self.assertEqual(frappe.db.count(TEMPLATE), 1)
		self.assertEqual(frappe.db.count("Employee Document Type"), types)
		self.assertEqual(self.company_counts(), counts)

	def test_install_creates_nothing_company_specific(self):
		before = self.company_counts()
		install.after_install()
		self.assertEqual(self.company_counts(), before)

	def test_the_aadhaar_field_exists(self):
		self.assertTrue(frappe.db.exists("Custom Field", "Employee-aadhaar_number"))

	def test_v16_navigation_records_are_the_apps_own(self):
		if frappe.db.exists("DocType", "Sidebar") or not frappe.db.exists("DocType", "Workspace Sidebar"):
			self.skipTest("v16 only")
		for doctype in ("Workspace Sidebar", "Desktop Icon"):
			row = frappe.db.get_value(doctype, "Document Collection", ["app", "standard"], as_dict=True)
			self.assertEqual((row.app, row.standard), ("hrms", 1), doctype)

	# M-8: what v16's migrate sweep deletes, the after-migrate hook puts back.
	def test_the_navigation_is_shipped_again_after_the_sweep(self):
		if frappe.db.exists("DocType", "Sidebar") or not frappe.db.exists("DocType", "Workspace Sidebar"):
			self.skipTest("v16 only")
		for doctype in ("Workspace Sidebar", "Desktop Icon"):
			frappe.delete_doc(doctype, "Document Collection", force=True, ignore_permissions=True)
		install.ship_desk_navigation()
		for doctype in ("Workspace Sidebar", "Desktop Icon"):
			row = frappe.db.get_value(doctype, "Document Collection", ["app", "standard"], as_dict=True)
			self.assertEqual((row.app, row.standard), ("hrms", 1), doctype)
		items = frappe.get_all(
			"Workspace Sidebar Item", filters={"parent": "Document Collection"}, pluck="link_to"
		)
		self.assertIn("Document Collection Template", items)

	# Uninstall removes navigation by `app`; the shipped rows are filed under hrms.
	def test_uninstall_removes_the_shipped_navigation(self):
		if frappe.db.exists("DocType", "Sidebar") or not frappe.db.exists("DocType", "Workspace Sidebar"):
			self.skipTest("v16 only")
		install.before_uninstall()
		for doctype in ("Workspace Sidebar", "Desktop Icon"):
			self.assertFalse(frappe.db.exists(doctype, "Document Collection"), doctype)
		install.ship_desk_navigation()
		for doctype in ("Workspace Sidebar", "Desktop Icon"):
			self.assertTrue(frappe.db.exists(doctype, "Document Collection"), doctype)

	# M17: desk users who cannot open the request do not see its links.
	def test_the_navigation_is_for_hr_roles(self):
		from pathlib import Path

		app = Path(install.__file__).resolve().parent
		for path in (
			app / "document_collection" / "workspace" / "document_collection" / "document_collection.json",
			app / "desktop_icon" / "document_collection.json",
		):
			roles = {r["role"] for r in frappe.parse_json(path.read_text())["roles"]}
			self.assertEqual(roles, {"HR User", "HR Manager"}, path.name)

	@staticmethod
	def company_counts():
		return {dt: frappe.db.count(dt) for dt in COMPANY_DOCTYPES}

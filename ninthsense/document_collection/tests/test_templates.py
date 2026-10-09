"""US5: templates, their mapping, and picking one at Send (T081, FR-040 to FR-044, R24)."""

import frappe
from frappe.model.mapper import make_mapped_doc
from frappe.utils import getdate, today

from ninthsense import install
from ninthsense.core.mapping_rows import DEFAULT_MAPPING_ROWS
from ninthsense.core.mapping_rules import NEW_JOB_FIELDS
from ninthsense.document_collection import hr_api, service
from ninthsense.document_collection.tests.error_logs import AppTestCase
from ninthsense.document_collection.tests.portal_harness import PortalTestCase, png_bytes

TEMPLATE = "Document Collection Template"
REQUEST = "Document Collection Request"
PORTAL_URL = "http://localhost:3000"
SECRET = "ef" * 32
SAVEPOINT = "nso_templates_test"
PREVIOUS_JOB = ("Offer Letter", "Latest Pay Slip")
NATIVE = "hrms.hr.doctype.employee_onboarding.employee_onboarding.make_employee"


def make_template(name, documents, mapping=(), is_default=0, is_enabled=1):
	"""`documents` as `(type, mandatory)`, `mapping` as `(field_key, source type, fallback type)`."""
	return frappe.get_doc(
		{
			"doctype": TEMPLATE,
			"template_name": name,
			"is_enabled": is_enabled,
			"is_default": is_default,
			"documents": [{"document_type": d, "is_mandatory": m} for d, m in documents],
			"field_mapping": [
				{"field_key": k, "source_document": s, "fallback_document": f} for k, s, f in mapping
			],
		}
	).insert(ignore_permissions=True)


FOREIGN = (("Passport", 1), ("PAN Card", 1), ("Resume", 0))


class TestTemplates(AppTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		install.after_install()
		settings = frappe.get_single("Document Collection Settings")
		settings.portal_url = PORTAL_URL
		settings.callback_secret = SECRET
		settings.save(ignore_permissions=True)
		for name in frappe.get_all("Email Account", filters={"default_outgoing": 1}, pluck="name"):
			frappe.db.set_value("Email Account", name, "default_outgoing", 0)
		cls.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		if not frappe.db.exists("Designation", "Engineer"):
			frappe.get_doc({"doctype": "Designation", "designation_name": "Engineer"}).insert()

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.savepoint(SAVEPOINT)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback(save_point=SAVEPOINT)

	def make_onboarding(self):
		applicant = frappe.get_doc(
			{
				"doctype": "Job Applicant",
				"applicant_name": "Template Candidate",
				"email_id": f"candidate-{frappe.generate_hash(length=8)}@example.com",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		offer = frappe.get_doc(
			{
				"doctype": "Job Offer",
				"job_applicant": applicant.name,
				"applicant_name": applicant.applicant_name,
				"offer_date": today(),
				"designation": "Engineer",
				"company": self.company,
				"status": "Awaiting Response",
			}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Employee Onboarding",
				"job_applicant": applicant.name,
				"job_offer": offer.name,
				"company": self.company,
				"designation": "Engineer",
				"date_of_joining": today(),
				"boarding_begins_on": today(),
			}
		).insert(ignore_permissions=True)

	def send(self, onboarding, template=None):
		kwargs = {"template": template} if template else {}
		return hr_api.send_onboarding_link(employee_onboarding=onboarding, **kwargs)

	def assert_refused(self, fn, text):
		with self.assertRaises(frappe.ValidationError) as raised:
			fn()
		self.assertIn(text, str(raised.exception))

	def foreign(self, **kwargs):
		return make_template("Foreign national", FOREIGN, **kwargs)

	# (a) FR-044
	def test_install_seeds_one_default_standard_onboarding(self):
		self.assertEqual(frappe.get_all(TEMPLATE, pluck="name"), [install.DEFAULT_TEMPLATE])
		template = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		self.assertEqual((template.is_enabled, template.is_default), (1, 1))
		self.assertEqual(
			[(r.document_type, r.is_mandatory) for r in template.documents],
			list(install.DEFAULT_TEMPLATE_DOCUMENTS),
		)
		name_of = dict(
			frappe.get_all("Employee Document Type", fields=["document_code", "name"], as_list=True)
		)
		self.assertEqual(
			[(r.field_key, r.source_document, r.fallback_document) for r in template.field_mapping],
			[(k, name_of[s], name_of.get(f)) for k, s, f in DEFAULT_MAPPING_ROWS],
		)
		for row in template.documents:
			defaults = frappe.db.get_value(
				"Employee Document Type",
				row.document_type,
				["default_allowed_file_types", "default_max_file_size_mb"],
			)
			self.assertEqual((row.allowed_file_types, row.max_file_size_mb), defaults)

	def test_seeding_again_creates_nothing(self):
		install.seed_default_template()
		self.assertEqual(frappe.db.count(TEMPLATE), 1)

	# (b) FR-041
	def test_a_new_default_clears_the_old_one(self):
		self.foreign(is_default=1)
		self.assertEqual(
			frappe.get_all(TEMPLATE, filters={"is_default": 1}, pluck="name"), ["Foreign national"]
		)

	# (c) FR-041, amended by the I-2 ruling: deleting the default promotes another (below).
	def test_the_default_cannot_be_disabled_or_unset_while_another_is_enabled(self):
		self.foreign()
		standard = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		standard.is_enabled = 0
		self.assert_refused(lambda: standard.save(ignore_permissions=True), "cannot be disabled")

		standard.reload()
		standard.is_default = 0
		self.assert_refused(lambda: standard.save(ignore_permissions=True), "must be a default")

	# I-2: deleting the default hands it to the oldest other enabled template.
	def test_deleting_the_default_promotes_the_oldest_enabled_template(self):
		self.foreign()
		make_template("Fresher", (("Resume", 1),))
		frappe.delete_doc(TEMPLATE, install.DEFAULT_TEMPLATE, ignore_permissions=True)
		self.assert_one_default("Foreign national")

	# I-2: unticking the default with no other enabled template keeps it; enabling another
	# template later still finds exactly one default.
	def test_unticking_the_only_enabled_default_keeps_it(self):
		self.foreign(is_enabled=0)
		standard = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		standard.is_default = 0
		standard.save(ignore_permissions=True)
		self.assertEqual(standard.is_default, 1)
		foreign = frappe.get_doc(TEMPLATE, "Foreign national")
		foreign.is_enabled = 1
		foreign.save(ignore_permissions=True)
		self.assert_one_default(install.DEFAULT_TEMPLATE)

	# I-2: the first template on a site, and the first after the last was deleted, is the default.
	def test_the_first_template_becomes_the_default(self):
		frappe.delete_doc(TEMPLATE, install.DEFAULT_TEMPLATE, ignore_permissions=True)
		self.assertEqual(self.foreign().is_default, 1)
		self.assert_one_default("Foreign national")

	# I-2: with no other enabled template, the default may be disabled; it stops being the default,
	# and is the default again once re-enabled.
	def test_disabling_the_last_enabled_template_clears_its_default(self):
		standard = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		standard.is_enabled = 0
		standard.save(ignore_permissions=True)
		self.assertEqual(standard.is_default, 0)
		standard.is_enabled = 1
		standard.save(ignore_permissions=True)
		self.assert_one_default(install.DEFAULT_TEMPLATE)

	def assert_one_default(self, name):
		self.assertEqual(
			frappe.get_all(TEMPLATE, filters={"is_enabled": 1, "is_default": 1}, pluck="name"), [name]
		)

	def test_a_disabled_template_cannot_be_default(self):
		self.assert_refused(lambda: self.foreign(is_default=1, is_enabled=0), "disabled template cannot be")

	def test_a_template_needs_documents_without_repeats(self):
		self.assert_refused(lambda: make_template("Empty", ()), "at least one document")
		self.assert_refused(
			lambda: make_template("Twice", (("Resume", 1), ("Resume", 0))), "Resume is listed twice"
		)

	# The grid shows the rules a row will use, not an empty cell and a 0.
	def test_a_row_left_empty_takes_the_document_types_file_rules(self):
		template = frappe.get_doc(
			{
				"doctype": TEMPLATE,
				"template_name": "File Rules",
				"documents": [
					{"document_type": "Passport", "is_mandatory": 1},
					{"document_type": "PAN Card", "allowed_file_types": "pdf", "max_file_size_mb": 5},
				],
			}
		).insert(ignore_permissions=True)
		passport, pan = template.documents
		defaults = frappe.db.get_value(
			"Employee Document Type",
			"Passport",
			["default_allowed_file_types", "default_max_file_size_mb"],
		)
		self.assertTrue(all(defaults))
		self.assertEqual((passport.allowed_file_types, passport.max_file_size_mb), tuple(defaults))
		self.assertEqual((pan.allowed_file_types, pan.max_file_size_mb), ("pdf", 5))

	# M-3: a padded key is stored as the catalogue spells it.
	def test_a_padded_field_key_is_stored_bare(self):
		template = self.foreign(mapping=((" pan_number ", "PAN Card", None),))
		self.assertEqual([r.field_key for r in template.field_mapping], ["pan_number"])

	# (d) FR-042, FR-043
	def test_a_bad_mapping_row_is_refused_with_the_reason(self):
		self.assert_refused(
			lambda: self.foreign(mapping=(("bank_ac_no", "Cancelled Cheque", None),)),
			"source Cancelled Cheque is not one of the documents this template asks for",
		)
		self.assert_refused(
			lambda: self.foreign(
				mapping=(("pan_number", "PAN Card", None), ("pan_number", "PAN Card", None))
			),
			"PAN (pan_number) is mapped more than once",
		)
		self.assert_refused(
			lambda: make_template(
				"Previous job", (("Offer Letter", 1),), mapping=(("designation", "Offer Letter", None),)
			),
			"source Offer Letter describes the previous job",
		)

	def test_every_problem_is_listed_in_one_message(self):
		with self.assertRaises(frappe.ValidationError) as raised:
			self.foreign(
				mapping=(
					("bank_ac_no", "Cancelled Cheque", None),
					("pan_number", "PAN Card", "PAN Card"),
				)
			)
		self.assertIn("bank_ac_no", str(raised.exception))
		self.assertIn("pan_number", str(raised.exception))

	# (e) FR-043
	def test_the_editor_never_offers_the_previous_job_for_the_new_one(self):
		options = hr_api.get_mapping_options()
		by_key = {f["key"]: f for f in options["fields"]}
		for key in NEW_JOB_FIELDS:
			for document in PREVIOUS_JOB:
				self.assertNotIn(document, by_key.get(key, {}).get("documents", []), key)
		self.assertIn("Passport", by_key["first_name"]["documents"])
		self.assertTrue(
			{f["section"] for f in options["fields"]} <= {s["value"] for s in options["sections"]}
		)

	# Ruling: the editor's options need only the HR role, so templates can be set up before the
	# portal is configured. Send still needs complete Settings.
	def test_the_editor_options_need_no_settings_but_send_does(self):
		onboarding = self.make_onboarding()
		frappe.db.set_single_value("Document Collection Settings", "portal_url", "")
		try:
			self.assertTrue(hr_api.get_mapping_options()["fields"])
			self.assert_refused(
				lambda: hr_api.get_send_options(employee_onboarding=onboarding.name), "Portal URL"
			)
		finally:
			frappe.db.set_single_value("Document Collection Settings", "portal_url", PORTAL_URL)

	# M-4: a template whose every type was disabled since it was saved asks for nothing.
	def test_a_template_with_no_enabled_document_refuses_send(self):
		make_template("Resume only", (("Resume", 1),))
		frappe.db.set_value("Employee Document Type", "Resume", "is_enabled", 0)
		onboarding = self.make_onboarding()
		self.assert_refused(
			lambda: self.send(onboarding.name, "Resume only"),
			"The template Resume only asks for no enabled document.",
		)
		self.assertFalse(service.find_request(onboarding.name))

	# (f) FR-040
	def test_two_templates_need_a_pick_and_the_pick_is_used(self):
		self.foreign()
		onboarding = self.make_onboarding()
		self.assert_refused(
			lambda: self.send(onboarding.name), "Pick an enabled document collection template."
		)
		self.assertFalse(service.find_request(onboarding.name))

		options = hr_api.get_send_options(employee_onboarding=onboarding.name)
		self.assertEqual(
			options,
			{
				"templates": [
					{"name": install.DEFAULT_TEMPLATE, "is_default": 1},
					{"name": "Foreign national", "is_default": 0},
				],
				"current_template": None,
			},
		)

		answer = self.send(onboarding.name, "Foreign national")
		request = frappe.get_doc(REQUEST, answer["request"])
		self.assertEqual(request.template, "Foreign national")
		self.assertEqual(
			[(r.document_type, r.is_mandatory) for r in request.requested_documents], list(FOREIGN)
		)
		self.assertEqual(
			hr_api.get_send_options(employee_onboarding=onboarding.name)["current_template"],
			"Foreign national",
		)

	def test_a_disabled_or_unknown_template_is_refused(self):
		self.foreign(is_enabled=0)
		onboarding = self.make_onboarding()
		for name in ("Foreign national", "No such template"):
			self.assert_refused(lambda n=name: self.send(onboarding.name, n), "Pick an enabled")
		self.assertFalse(service.find_request(onboarding.name))

	# (g) FR-040
	def test_the_only_enabled_template_is_used_without_asking(self):
		self.foreign(is_default=1)
		frappe.db.set_value(TEMPLATE, install.DEFAULT_TEMPLATE, "is_enabled", 0)
		onboarding = self.make_onboarding()
		answer = self.send(onboarding.name)
		self.assertEqual(frappe.db.get_value(REQUEST, answer["request"], "template"), "Foreign national")

	# (h) FR-040
	def test_no_enabled_template_refuses_send(self):
		frappe.db.set_value(TEMPLATE, install.DEFAULT_TEMPLATE, "is_enabled", 0)
		onboarding = self.make_onboarding()
		self.assert_refused(
			lambda: self.send(onboarding.name), "Create a document collection template first."
		)
		self.assertFalse(service.find_request(onboarding.name))

	# (i) FR-040
	def test_a_resend_with_another_template_resnapshots_the_documents(self):
		onboarding = self.make_onboarding()
		answer = self.send(onboarding.name)
		self.assertEqual(
			frappe.db.get_value(REQUEST, answer["request"], "template"), install.DEFAULT_TEMPLATE
		)

		self.foreign()
		self.send(onboarding.name, "Foreign national")
		request = frappe.get_doc(REQUEST, answer["request"])
		self.assertEqual(request.template, "Foreign national")
		self.assertEqual([r.document_type for r in request.requested_documents], [d for d, _m in FOREIGN])


# The documents name someone the default mapping disagrees with; the passport names the applicant.
# A passport surname is the last name whole, never split (the Name Part ruling).
APPLICANT = "Asha Sen Verma"


def submit_onboarding(case):
	"""Submitting needs a holiday list; this one is rolled back with the class."""
	year = getdate(today()).year
	holiday_list = frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": f"NSO Test {frappe.generate_hash(length=6)}",
			"from_date": f"{year}-01-01",
			"to_date": f"{year + 1}-12-31",
		}
	).insert(ignore_permissions=True)
	case.onboarding.reload()
	case.onboarding.holiday_list = holiday_list.name
	case.onboarding.submit()
	case.commit()


def create_employee(case):
	frappe.local.message_log = []
	return make_mapped_doc(NATIVE, case.onboarding.name)


class TestLiveMapping(PortalTestCase):
	"""(j) US5 AS-5: Create Employee reads the template's mapping as it stands then (R24)."""

	def test_an_edited_mapping_changes_the_next_fill(self):
		for i, code in enumerate(("aadhaar_front", "pan_card")):
			self.assertEqual(self.upload(code, png_bytes(i + 1), vdid=f"doc-{code}").status, 200)
		payload = self.completion()
		extracted = {d["document_code"]: d["extracted"] for d in payload["steps"][0]["documents"]}
		extracted["aadhaar_front"]["name"] = "Ravi Kumar Shah"
		extracted["pan_card"]["name"] = "Ravi Kumar Shah"
		extracted["passport"].update(given_name="Asha", surname="Sen Verma")
		self.assertEqual(self.deliver(payload).status, 200)
		submit_onboarding(self)
		# After the submit, which would fetch the applicant's name again.
		frappe.db.set_value("Employee Onboarding", self.onboarding.name, "employee_name", APPLICANT)

		doc = create_employee(self)
		self.assertFalse(doc.first_name or doc.last_name)

		template = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		template.field_mapping = [r for r in template.field_mapping if r.field_key not in self.NAME_KEYS]
		for key in ("first_name", "last_name"):
			template.append("field_mapping", {"field_key": key, "source_document": "Passport"})
		template.save(ignore_permissions=True)
		self.commit()

		doc = create_employee(self)
		self.assertEqual((doc.employee_name, doc.first_name, doc.last_name), (APPLICANT, "Asha", "Sen Verma"))
		self.assertFalse(doc.middle_name)
		self.assertEqual(
			frappe.db.get_value(REQUEST, self.request_name, "template"), install.DEFAULT_TEMPLATE
		)

	NAME_KEYS = ("first_name", "middle_name", "last_name")

	# M-5: a template with no mapping says so instead of reporting "Filled 0".
	def test_no_mapping_is_named_and_fills_nothing(self):
		self.assertEqual(self.deliver(self.completion()).status, 200)
		submit_onboarding(self)
		template = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
		template.field_mapping = []
		template.save(ignore_permissions=True)
		self.commit()

		doc = create_employee(self)
		self.assertFalse(doc.first_name or doc.pan_number)
		messages = [str(m) for m in frappe.local.message_log]
		self.assertTrue(any("has no field mapping" in m for m in messages), messages)
		self.assertFalse(any("Filled" in m for m in messages), messages)
		self.assertFalse(frappe.get_doc(REQUEST, self.request_name).fill_results)


NO_CHEQUE = "No cheque"
IMAGE_CODES = ("aadhaar_front", "pan_card", "graduation_certificate", "cancelled_cheque")


class TestResendKeepsTheDelivery(PortalTestCase):
	"""I-1: a resend whose template drops a delivered document keeps that delivery until the next."""

	def setUp(self):
		super().setUp()
		if not frappe.db.exists(TEMPLATE, NO_CHEQUE):
			standard = frappe.get_doc(TEMPLATE, install.DEFAULT_TEMPLATE)
			make_template(
				NO_CHEQUE,
				[
					(r.document_type, r.is_mandatory)
					for r in standard.documents
					if r.document_type != "Cancelled Cheque"
				],
				[
					(r.field_key, r.source_document, r.fallback_document)
					for r in standard.field_mapping
					if r.source_document != "Cancelled Cheque"
				],
			)
		frappe.db.set_value(TEMPLATE, NO_CHEQUE, "is_enabled", 1)
		# Kept through the portal calls' rollbacks.
		self.commit()
		# The next test's set-up sends without naming a template, so one is enabled again.
		self.addCleanup(frappe.db.set_value, TEMPLATE, NO_CHEQUE, "is_enabled", 0)

	def deliver_all(self):
		for i, code in enumerate(IMAGE_CODES):
			self.assertEqual(self.upload(code, png_bytes(i + 1), vdid=f"doc-{code}").status, 200)
		self.assertEqual(self.deliver(self.completion()).status, 200)

	def resend_without_the_cheque(self):
		answer = service.send_link(self.onboarding.name, {"portal_url": PORTAL_URL}, template=NO_CHEQUE)
		self.commit()
		self.code = answer["link"].rsplit("/s/", 1)[1]

	def cheque(self):
		return next(
			(r for r in self.request().requested_documents if r.document_code == "cancelled_cheque"), None
		)

	def test_the_dropped_document_is_kept_shown_unrequested_and_attached(self):
		self.deliver_all()
		self.resend_without_the_cheque()

		row = self.cheque()
		self.assertEqual(row.is_requested, 0)
		self.assertTrue(row.file)
		self.assertEqual(self.request().template, NO_CHEQUE)
		descriptor = self.get_request().message
		codes = [d["document_code"] for d in descriptor["steps"][0]["documents"]]
		self.assertNotIn("cancelled_cheque", codes)
		self.assertIn("aadhaar_front", codes)
		# Not addressable by the new link.
		self.assertEqual(self.upload("cancelled_cheque", png_bytes(9)).status, 417)

		submit_onboarding(self)
		employee = create_employee(self)
		employee.insert()
		attached = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Employee", "attached_to_name": employee.name},
			pluck="file_url",
		)
		self.assertIn(row.file, attached)
		self.assertEqual(len(attached), len(IMAGE_CODES))

	def test_the_next_delivery_drops_the_row_and_its_file(self):
		self.deliver_all()
		self.resend_without_the_cheque()
		file_url = self.cheque().file

		self.assertEqual(self.upload("aadhaar_front", png_bytes(7), vdid="doc-again").status, 200)
		self.assertEqual(self.deliver(self.completion()).status, 200)

		self.assertIsNone(self.cheque())
		self.assertFalse(
			frappe.db.exists(
				"File",
				{"file_url": file_url, "attached_to_doctype": REQUEST, "attached_to_name": self.request_name},
			)
		)
		self.assertTrue(all(r.is_requested for r in self.request().requested_documents))

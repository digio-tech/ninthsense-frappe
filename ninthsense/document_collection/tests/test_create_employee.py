"""US3 end to end: Create > Employee fills the unsaved form, saving completes the request (T066)."""

import json
from pathlib import Path
from unittest import mock

import frappe
from frappe.core.doctype.file.file import File
from frappe.model.mapper import make_mapped_doc
from frappe.utils import get_bench_path, getdate, today

from ninthsense.core.fill import ALREADY_FILLED, ATTACH_FAILED, FILLED, INVALID
from ninthsense.document_collection import service
from ninthsense.document_collection.tests.portal_harness import PortalTestCase, png_bytes

NATIVE = "hrms.hr.doctype.employee_onboarding.employee_onboarding.make_employee"
# Rows whose allowed types include png in the seeded list.
IMAGE_CODES = ("aadhaar_front", "pan_card", "graduation_certificate", "cancelled_cheque")
FULL_AADHAAR = "999988887777"


class TestCreateEmployee(PortalTestCase):
	# ----------------------------------------------------------------- set-up

	def submit(self, onboarding):
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
		onboarding.reload()
		onboarding.holiday_list = holiday_list.name
		onboarding.submit()
		self.commit()

	def receive(self, edit=None):
		"""Stage the image documents, deliver the fixture (optionally edited) and submit."""
		for i, code in enumerate(IMAGE_CODES):
			answer = self.upload(code, png_bytes(i + 1), vdid=f"doc-{code}")
			self.assertEqual(answer.status, 200, answer)
		payload = self.completion()
		if edit:
			edit({d["document_code"]: d["extracted"] for d in payload["steps"][0]["documents"]}, payload)
		answer = self.deliver(payload)
		self.assertEqual(answer.status, 200, answer)
		self.assertEqual(self.request().status, "Data Received")
		self.submit(self.onboarding)

	def create(self):
		frappe.local.message_log = []
		return make_mapped_doc(NATIVE, self.onboarding.name)

	def report(self):
		return {row.fieldname: row for row in self.request().fill_results}

	def messages(self):
		return [json.loads(m) if isinstance(m, str) else m for m in frappe.local.message_log]

	def applicant_email(self):
		return frappe.db.get_value("Job Applicant", self.onboarding.job_applicant, "email_id")

	# ------------------------------------------------------------------- fill

	# (a)
	def test_the_form_opens_unsaved_with_native_values_and_the_fill(self):
		self.receive()
		from hrms.hr.doctype.employee_onboarding.employee_onboarding import make_employee as native

		plain = native(self.onboarding.name)
		doc = self.create()

		self.assertTrue(doc.is_new())
		self.assertTrue(doc.get("__islocal"))
		self.assertEqual(doc.employee_name, plain.employee_name)
		self.assertEqual(doc.employee_name, "Asha Rani Verma")
		self.assertEqual(doc.personal_email, self.applicant_email())
		self.assertEqual((doc.first_name, doc.middle_name, doc.last_name), ("Asha", "Rani", "Verma"))
		self.assertEqual(doc.gender, "Female")
		self.assertEqual(str(doc.date_of_birth), "1996-04-18")
		self.assertEqual(doc.aadhaar_number, "XXXX XXXX 7777")
		self.assertEqual(doc.pan_number, "ABCPV1234F")
		self.assertEqual(doc.bank_ac_no, "50100000000001")
		self.assertEqual(doc.ifsc_code, "HDFC0000001")
		self.assertEqual(doc.micr_code, "560240001")
		self.assertEqual(doc.provident_fund_account, "KA/BLR/0000001/000/0000001")
		self.assertEqual(len(doc.education), 1)
		self.assertEqual(doc.education[0].year_of_passing, 2018)
		self.assertEqual(doc.education[0].qualification, "B.E. Computer Science")
		self.assertEqual(len(doc.external_work_history), 1)
		self.assertEqual(doc.external_work_history[0].company_name, "Digio India")
		# Never filled: the previous job's designation, and every check box.
		self.assertEqual(doc.designation, plain.designation)
		for df in doc.meta.fields:
			if df.fieldtype == "Check":
				self.assertEqual(doc.get(df.fieldname), plain.get(df.fieldname), df.fieldname)

		request = self.request()
		self.assertTrue(request.last_fill_on)
		self.assertEqual(self.report()["pan_number"].outcome, FILLED)
		# FR-027: the data stays as it was.
		self.assertEqual(request.status, "Data Received")
		self.assertTrue(request.extractions)

		(message,) = [m for m in self.messages() if "Filled" in m.get("message", "")]
		self.assertEqual(message.get("indicator"), "green")
		self.assertIn(request.name, message["message"])
		self.assertNotIn("9thSense's result", message["message"])

	# I1: the documents name someone else.
	def test_a_different_name_is_reported_and_the_parts_are_left_empty(self):
		self.receive(lambda extracted, payload: extracted["aadhaar_front"].update(name="Ravi Kumar Shah"))
		doc = self.create()
		self.assertEqual(doc.employee_name, "Asha Rani Verma")
		self.assertFalse(doc.first_name or doc.middle_name or doc.last_name)
		report = self.report()
		row = report["employee_name"]
		self.assertEqual(
			(row.outcome, row.field_label, row.value, row.existing_value),
			(ALREADY_FILLED, "Employee Name", "Ravi Kumar Shah", "Asha Rani Verma"),
		)
		for part in ("first_name", "middle_name", "last_name"):
			self.assertNotIn(part, report)
		self.assertEqual(report["pan_number"].outcome, FILLED)
		(message,) = [m for m in self.messages() if "Filled" in m.get("message", "")]
		self.assertIn("Ravi Kumar Shah", message["message"])
		self.assertIn("not <strong>Asha Rani Verma</strong>", message["message"])
		# The report link ends its sentence; the mismatch starts the next one.
		self.assertRegex(message["message"], r"Fill report: <a [^>]+>[^<]+</a>\. The documents name ")

	# (b)
	def test_a_different_resume_email_is_reported_already_filled(self):
		self.receive()
		self.create()
		row = self.report()["personal_email"]
		self.assertEqual(row.outcome, ALREADY_FILLED)
		self.assertEqual(row.value, "asha.verma@example.com")
		self.assertEqual(row.existing_value, self.applicant_email())

	# (c)
	def test_an_unknown_gender_and_a_bad_year_are_skipped_invalid(self):
		def edit(extracted, payload):
			extracted["aadhaar_front"]["gender"] = "Q"
			extracted["graduation_certificate"]["year_of_passing"] = "20X5"

		genders = frappe.db.count("Gender")
		self.receive(edit)
		doc = self.create()

		report = self.report()
		self.assertEqual(report["gender"].outcome, INVALID)
		self.assertEqual(report["gender"].reason, "no Gender named 'Q'")
		self.assertEqual(report["education.year_of_passing"].outcome, INVALID)
		self.assertFalse(doc.gender)
		self.assertNotIn("year_of_passing", {k for k, v in doc.education[0].as_dict().items() if v})
		self.assertEqual(frappe.db.count("Gender"), genders)
		self.assertFalse(frappe.db.exists("Gender", "Q"))

	def test_the_gender_code_m_resolves_to_the_existing_male_record(self):
		# The catalogue's Gender transform maps codes before the link check (R6).
		self.receive(lambda extracted, payload: extracted["aadhaar_front"].update(gender="M"))
		genders = frappe.db.count("Gender")
		self.assertEqual(self.create().gender, "Male")
		self.assertEqual(frappe.db.count("Gender"), genders)

	def test_a_result_that_is_not_passed_is_named(self):
		self.receive(lambda extracted, payload: payload.update(status="review"))
		self.create()
		(message,) = [m for m in self.messages() if "Filled" in m.get("message", "")]
		self.assertIn("9thSense's result: Needs Review.", message["message"])

	# (f)
	def test_create_twice_replaces_the_report(self):
		self.receive()
		self.create()
		first = [(r.outcome, r.fieldname, r.value) for r in self.request().fill_results]
		extractions = len(self.request().extractions)
		self.create()
		second = [(r.outcome, r.fieldname, r.value) for r in self.request().fill_results]
		self.assertEqual(first, second)
		self.assertEqual(len(self.request().extractions), extractions)

	# ------------------------------------------------------------------- save

	# (d)
	def test_saving_completes_the_request_and_attaches_each_file(self):
		self.receive()
		doc = self.create()
		doc.insert()

		request = self.request()
		self.assertEqual(request.status, "Completed")
		self.assertEqual(request.employee, doc.name)
		delivered = sorted(r.file for r in request.requested_documents if r.file)
		self.assertEqual(len(delivered), len(IMAGE_CODES))
		attached = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Employee", "attached_to_name": doc.name},
			fields=["file_url", "is_private"],
		)
		self.assertEqual(sorted(f.file_url for f in attached), delivered)
		self.assertTrue(all(f.is_private for f in attached))
		# The request keeps its own copy of each File.
		for url in delivered:
			self.assertTrue(
				frappe.db.exists("File", {"file_url": url, "attached_to_doctype": service.REQUEST})
			)
		self.assertNotIn(ATTACH_FAILED, [r.outcome for r in request.fill_results])

		# Scenario 17 / SC-005: the full number is nowhere.
		employee = frappe.get_doc("Employee", doc.name)
		self.assertEqual(employee.aadhaar_number, "XXXX XXXX 7777")
		for text in (frappe.as_json(request.as_dict()), frappe.as_json(employee.as_dict())):
			self.assertNotIn(FULL_AADHAAR, text)
		log = Path(get_bench_path()) / "logs" / "ninthsense.log"
		if log.exists():
			self.assertNotIn(FULL_AADHAAR, log.read_text())

	# (e)
	def test_a_failed_attach_is_reported_and_the_save_stands(self):
		self.receive()
		doc = self.create()
		bad = next(r for r in self.request().requested_documents if r.document_code == "pan_card")
		real_insert = File.insert

		def flaky(file_doc, *args, **kwargs):
			if file_doc.attached_to_doctype == "Employee" and file_doc.file_url == bad.file:
				frappe.throw("simulated failure")
			return real_insert(file_doc, *args, **kwargs)

		with mock.patch.object(File, "insert", flaky):
			doc.insert()

		self.assertTrue(frappe.db.exists("Employee", doc.name))
		request = self.request()
		self.assertEqual(request.status, "Completed")
		failed = [r for r in request.fill_results if r.outcome == ATTACH_FAILED]
		self.assertEqual(len(failed), 1)
		self.assertEqual(failed[0].field_label, bad.document_type)
		self.assertTrue(failed[0].reason)
		attached = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "Employee", "attached_to_name": doc.name},
			pluck="file_url",
		)
		self.assertEqual(len(attached), len(IMAGE_CODES) - 1)
		self.assertNotIn(bad.file, attached)
		self.assertFalse([m for m in frappe.local.message_log if "simulated failure" in str(m)])

	# (g)
	def test_before_the_data_arrives_only_native_values_and_a_warning(self):
		self.submit(self.onboarding)
		doc = self.create()

		self.assertTrue(doc.is_new())
		self.assertFalse(doc.first_name)
		self.assertFalse(doc.pan_number)
		self.assertFalse(doc.get("aadhaar_number"))
		self.assertFalse(doc.education)
		self.assertEqual(doc.personal_email, self.applicant_email())
		(message,) = self.messages()
		self.assertEqual(message.get("indicator"), "orange")
		self.assertIn("Saving this Employee closes their link", message["message"])
		self.assertEqual(self.request().status, "Link Sent")
		self.assertFalse(self.request().fill_results)

		# The ruling: saving anyway completes the request and closes the link (FR-026, FR-014).
		doc.update({"first_name": "Asha", "gender": "Female", "date_of_birth": "1996-04-18"})
		doc.insert()
		self.assertEqual(self.request().status, "Completed")
		self.assertEqual(self.request().employee, doc.name)
		closed = self.get_request()
		self.assertEqual((closed.status, closed.message["state"]), (200, "submitted"))

	def test_a_failing_fill_still_returns_the_native_employee(self):
		self.receive()
		frappe.local.message_log = []
		with mock.patch.object(service, "fill_employee", side_effect=RuntimeError("boom")):
			doc = make_mapped_doc(NATIVE, self.onboarding.name)
		self.assertEqual(doc.doctype, "Employee")
		self.assertTrue(doc.is_new())
		self.assertEqual(doc.employee_name, self.onboarding.employee_name)
		self.assertFalse(doc.get("aadhaar_number"))
		self.assertTrue(
			any("Couldn't fill" in str(m.get("message")) for m in frappe.local.message_log),
			frappe.local.message_log,
		)

	def test_no_request_means_native_behaviour(self):
		onboarding = self.make_onboarding()
		self.submit(onboarding)
		frappe.local.message_log = []
		doc = make_mapped_doc(NATIVE, onboarding.name)
		self.assertFalse(doc.first_name)
		self.assertEqual(frappe.local.message_log, [])

	def test_a_closed_request_means_native_behaviour(self):
		self.receive()
		self.create().insert()
		self.assertEqual(self.request().status, "Completed")
		fill_results = len(self.request().fill_results)
		# HRMS refuses a second Employee itself; the fill must not run either way.
		self.assertIsNone(service.fill_employee(frappe.new_doc("Employee"), self.onboarding.name))
		self.assertEqual(len(self.request().fill_results), fill_results)

	# M4: whoever HRMS lets create the Employee still can; only HR users get the fill.
	def test_a_user_without_an_hr_role_gets_the_native_employee(self):
		self.receive()
		frappe.local.message_log = []
		with mock.patch.object(frappe, "get_roles", return_value=["Onboarding Clerk"]):
			doc = make_mapped_doc(NATIVE, self.onboarding.name)
		self.assertTrue(doc.is_new())
		self.assertEqual(doc.employee_name, self.onboarding.employee_name)
		self.assertFalse(doc.first_name or doc.pan_number or doc.get("aadhaar_number"))
		self.assertEqual(frappe.local.message_log, [])
		self.assertFalse(self.request().fill_results)

	# M5: a fill that fails after writing its report leaves nothing behind.
	def test_a_fill_that_fails_late_leaves_no_report_and_no_green_notice(self):
		self.receive()
		real_log_event = service.log_event

		def failing(event, **fields):
			if event == "employee_filled":
				raise RuntimeError("late failure")
			return real_log_event(event, **fields)

		frappe.local.message_log = []
		with mock.patch.object(service, "log_event", side_effect=failing):
			doc = make_mapped_doc(NATIVE, self.onboarding.name)
		self.assertFalse(doc.get("pan_number"))
		self.assertFalse(self.request().fill_results)
		self.assertFalse(self.request().last_fill_on)
		messages = [str(m.get("message")) for m in self.messages()]
		self.assertEqual(len(messages), 1, messages)
		self.assertIn("Couldn't fill", messages[0])

	# M13: data from the earlier link, with a newer link out.
	def test_a_newer_open_link_is_warned_about(self):
		self.receive()
		self.code = self.send(self.onboarding.name)
		self.create()
		warnings = [m for m in self.messages() if "newer link" in m.get("message", "")]
		self.assertEqual(len(warnings), 1)
		self.assertEqual(warnings[0].get("indicator"), "orange")
		self.assertTrue(self.request().fill_results)

	def test_no_newer_link_no_warning(self):
		self.receive()
		self.create()
		self.assertFalse([m for m in self.messages() if "newer link" in m.get("message", "")])

	# ------------------------------------------------------------- Aadhaar (h)

	def test_a_full_aadhaar_number_is_masked_on_save(self):
		self.receive()
		doc = self.create()
		doc.insert()
		employee = frappe.get_doc("Employee", doc.name)
		employee.aadhaar_number = "123412341234"
		employee.save()
		self.assertEqual(frappe.db.get_value("Employee", doc.name, "aadhaar_number"), "XXXX XXXX 1234")
		employee.reload()
		employee.aadhaar_number = "1234"
		employee.save()
		self.assertEqual(frappe.db.get_value("Employee", doc.name, "aadhaar_number"), "unreadable")

	# ------------------------------------------------------------------ links

	def test_link_resolution_is_case_insensitive_and_company_scoped(self):
		self.assertEqual(service.resolve_link_value("Gender", "female", self.company), "Female")
		self.assertIsNone(service.resolve_link_value("Gender", "Nonexistent", self.company))
		department = frappe.get_doc(
			{"doctype": "Department", "department_name": "NSO Fill Test", "company": self.company}
		).insert(ignore_permissions=True)
		self.assertEqual(
			service.resolve_link_value("Department", "nso fill test", self.company), department.name
		)
		self.assertEqual(
			service.resolve_link_value("Department", department.name, self.company), department.name
		)
		self.assertIsNone(service.resolve_link_value("Department", "NSO Fill Test", "Another Company"))
		self.assertIsNone(service.resolve_link_value("Department", department.name, "Another Company"))

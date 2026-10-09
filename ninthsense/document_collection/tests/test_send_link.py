"""Send onboarding link (US1), end to end through hr_api on a real site."""

import hashlib
from unittest import mock

import frappe
from frappe.utils import add_days, get_datetime, today

from ninthsense import install
from ninthsense.document_collection import email, hr_api, service
from ninthsense.document_collection.tests.error_logs import AppTestCase

PORTAL_URL = "http://localhost:3000"
SECRET = "ab" * 32
REQUEST = "Document Collection Request"
EMPLOYEE_ONLY_USER = "nso-employee-only@example.com"


def _send(onboarding):
	return hr_api.send_onboarding_link(employee_onboarding=onboarding)


def _requests_for(onboarding):
	return frappe.get_all(REQUEST, filters={"employee_onboarding": onboarding}, pluck="name")


class TestSendLink(AppTestCase):
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

	def tearDown(self):
		frappe.set_user("Administrator")

	def make_onboarding(self):
		applicant = frappe.get_doc(
			{
				"doctype": "Job Applicant",
				"applicant_name": "Test Candidate",
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

	def assert_refused(self, onboarding, text, exc=frappe.ValidationError):
		with self.assertRaises(exc) as raised:
			_send(onboarding)
		self.assertIn(text, str(raised.exception))
		self.assertEqual(_requests_for(onboarding), [])

	# (a)
	def test_first_send_creates_one_request(self):
		onboarding = self.make_onboarding()
		answer = _send(onboarding.name)

		names = _requests_for(onboarding.name)
		self.assertEqual(len(names), 1)
		request = frappe.get_doc(REQUEST, names[0])
		self.assertEqual(answer["request"], request.name)
		self.assertEqual(request.status, "Link Sent")
		self.assertEqual(answer["status"], "Link Sent")
		self.assertEqual(
			get_datetime(request.link_expires_on), add_days(get_datetime(request.link_sent_on), 14)
		)
		self.assertTrue(request.link_ref.startswith(f"{request.name}."))
		self.assertEqual(request.job_applicant, onboarding.job_applicant)
		self.assertEqual(request.company, onboarding.company)
		self.assertEqual(request.onboarding_name, onboarding.name)

		template = frappe.get_doc(service.TEMPLATE, install.DEFAULT_TEMPLATE)
		self.assertEqual(request.template, template.name)
		self.assertEqual(
			[(r.document_type, r.is_mandatory) for r in request.requested_documents],
			[(r.document_type, r.is_mandatory) for r in template.documents],
		)
		for row in request.requested_documents:
			doc_type = frappe.get_doc("Employee Document Type", row.document_type)
			self.assertEqual(row.document_code, doc_type.document_code)
			self.assertEqual(row.display_group, doc_type.category)
			self.assertTrue(row.allowed_file_types)
			self.assertTrue(row.max_file_size_mb)

		# The link carries the code whose hash is stored, and nothing else is stored.
		self.assertTrue(answer["link"].startswith(f"{PORTAL_URL}/s/"))
		code = answer["link"].rsplit("/s/", 1)[1]
		self.assertEqual(request.link_code_hash, hashlib.sha256(code.encode()).hexdigest())
		self.assertNotIn(code, frappe.as_json(request.as_dict()))

	# (b)
	def test_resend_reuses_the_request_and_clears_staged_uploads(self):
		onboarding = self.make_onboarding()
		_send(onboarding.name)
		request = frappe.get_doc(REQUEST, _requests_for(onboarding.name)[0])
		first_hash, first_ref = request.link_code_hash, request.link_ref
		for row in request.requested_documents:
			row.staged_file = "/private/files/x.pdf"
			row.staged_file_name = "x.pdf"
			row.staged_file_size_bytes = 10
			row.staged_verification_document_id = "doc-1"
			row.staged_on = frappe.utils.now_datetime()
		request.requested_documents[0].file = "/private/files/delivered.pdf"
		request.replaced_verification_document_ids = '["doc-0"]'
		request.link_delivered_on = frappe.utils.now_datetime()
		# Set-up standing in for an upload and a delivery.
		request.flags.via_service = True
		request.save(ignore_permissions=True)

		_send(onboarding.name)

		self.assertEqual(_requests_for(onboarding.name), [request.name])
		request.reload()
		self.assertNotEqual(request.link_code_hash, first_hash)
		self.assertNotEqual(request.link_ref, first_ref)
		for row in request.requested_documents:
			for field in service.STAGED_FIELDS:
				self.assertFalse(row.get(field), f"{row.document_type}.{field}")
		self.assertFalse(request.replaced_verification_document_ids)
		self.assertFalse(request.link_delivered_on)
		# Delivered data stays until the next delivery replaces it.
		self.assertEqual(request.requested_documents[0].file, "/private/files/delivered.pdf")

	# (c)
	def test_a_racing_insert_becomes_a_resend(self):
		onboarding = self.make_onboarding()
		_send(onboarding.name)
		name = _requests_for(onboarding.name)[0]
		first_hash = frappe.db.get_value(REQUEST, name, "link_code_hash")

		real_find = service.find_request
		calls = []

		def not_visible_yet(onboarding_name, for_update=False):
			calls.append(for_update)
			if len(calls) == 1:
				return None
			return real_find(onboarding_name, for_update=for_update)

		frappe.clear_messages()
		with mock.patch.object(service, "find_request", side_effect=not_visible_yet):
			answer = _send(onboarding.name)

		self.assertEqual(calls, [False, True])
		self.assertEqual(_requests_for(onboarding.name), [name])
		self.assertEqual(answer["request"], name)
		self.assertNotEqual(frappe.db.get_value(REQUEST, name, "link_code_hash"), first_hash)
		self.assertFalse(frappe.local.message_log)

	# (d)
	def test_a_missing_or_malformed_email_is_refused(self):
		for bad in ("", "bad"):
			onboarding = self.make_onboarding()
			frappe.db.set_value("Job Applicant", onboarding.job_applicant, "email_id", bad)
			self.assert_refused(onboarding.name, "no valid email address")

	# (e)
	def test_an_empty_portal_url_is_refused(self):
		onboarding = self.make_onboarding()
		frappe.db.set_single_value("Document Collection Settings", "portal_url", "")
		try:
			self.assert_refused(onboarding.name, "Portal URL")
		finally:
			frappe.db.set_single_value("Document Collection Settings", "portal_url", PORTAL_URL)

	# (f)
	def test_a_cancelled_onboarding_is_refused(self):
		onboarding = self.make_onboarding()
		frappe.db.set_value("Employee Onboarding", onboarding.name, "docstatus", 2)
		self.assert_refused(onboarding.name, "cancelled")

	def test_an_onboarding_with_an_employee_is_refused(self):
		onboarding = self.make_onboarding()
		frappe.db.set_value("Employee Onboarding", onboarding.name, "employee", "HR-EMP-NSO-TEST")
		self.assert_refused(onboarding.name, "already has an Employee")

	# (g)
	def test_a_user_with_only_the_employee_role_is_refused(self):
		onboarding = self.make_onboarding()
		if not frappe.db.exists("User", EMPLOYEE_ONLY_USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": EMPLOYEE_ONLY_USER,
					"first_name": "Employee Only",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Employee")
		frappe.set_user(EMPLOYEE_ONLY_USER)
		with self.assertRaises(frappe.PermissionError):
			_send(onboarding.name)
		with self.assertRaises(frappe.PermissionError):
			hr_api.get_onboarding_request(employee_onboarding=onboarding.name)
		frappe.set_user("Administrator")
		self.assertEqual(_requests_for(onboarding.name), [])

	# (h)
	def test_without_an_outgoing_account_the_link_is_returned(self):
		onboarding = self.make_onboarding()
		self.assertFalse(email.has_outgoing_email_account())
		answer = _send(onboarding.name)
		self.assertFalse(answer["email_sent"])
		self.assertTrue(answer["link"].startswith(f"{PORTAL_URL}/s/"))
		self.assertEqual(frappe.db.get_value(REQUEST, answer["request"], "link_emailed"), 0)

	def test_a_sent_email_hides_the_link_and_renders_the_template(self):
		onboarding = self.make_onboarding()
		queue = mock.Mock(name="queue")
		with (
			mock.patch.object(email, "has_outgoing_email_account", return_value=True),
			mock.patch.object(email, "_queue_sent", return_value=True),
			mock.patch.object(frappe, "sendmail", return_value=queue) as sendmail,
		):
			answer = _send(onboarding.name)

		self.assertTrue(answer["email_sent"])
		self.assertNotIn("link", answer)
		queue.send.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertFalse(kwargs["now"])
		applicant_email = frappe.db.get_value("Job Applicant", onboarding.job_applicant, "email_id")
		self.assertEqual(kwargs["recipients"], [applicant_email])
		self.assertIn(f"{PORTAL_URL}/s/", kwargs["message"])
		self.assertIn("Test Candidate", kwargs["message"])
		self.assertIn("Engineer", kwargs["message"])
		self.assertEqual(kwargs["subject"], f"Complete your onboarding for {self.company}")
		self.assertEqual(frappe.db.get_value(REQUEST, answer["request"], "link_emailed"), 1)

	# M8: an invite that did not go out is not retried later, and its body is dropped.
	def test_an_unsent_invite_is_stopped_and_redacted(self):
		onboarding = self.make_onboarding()
		queue = frappe.get_doc(
			{
				"doctype": "Email Queue",
				"status": "Not Sent",
				"message": "Subject: Invite\nContent-Type: text/plain\n\nhttp://localhost:3000/s/LIVECODE",
			}
		).insert(ignore_permissions=True)
		queue.send = mock.Mock()  # leaves it Not Sent, as a suspended queue or muted mail does
		with (
			mock.patch.object(email, "has_outgoing_email_account", return_value=True),
			mock.patch.object(frappe, "sendmail", return_value=queue) as sendmail,
			# Email Queue's redaction commits; here that would keep the test's records.
			mock.patch.object(frappe.db, "commit"),
		):
			answer = _send(onboarding.name)

		self.assertFalse(answer["email_sent"])
		self.assertTrue(sendmail.call_args.kwargs["redact_message_after_send"])
		row = frappe.db.get_value("Email Queue", queue.name, ["status", "message"], as_dict=True)
		self.assertEqual(row.status, "Error")
		self.assertNotIn("LIVECODE", row.message)

	def test_get_onboarding_request_reports_state_only(self):
		onboarding = self.make_onboarding()
		self.assertIsNone(hr_api.get_onboarding_request(employee_onboarding=onboarding.name))
		_send(onboarding.name)
		state = hr_api.get_onboarding_request(employee_onboarding=onboarding.name)
		self.assertEqual(set(state), {"name", "status", "link_emailed", "link_expires_on"})
		self.assertEqual(state["status"], "Link Sent")

	def test_a_closed_request_is_refused(self):
		onboarding = self.make_onboarding()
		answer = _send(onboarding.name)
		frappe.db.set_value(REQUEST, answer["request"], "status", "Completed")
		with self.assertRaises(frappe.ValidationError) as raised:
			_send(onboarding.name)
		self.assertIn("This request is closed (Completed).", str(raised.exception))

	def test_a_missing_email_names_the_applicant(self):
		onboarding = self.make_onboarding()
		frappe.db.set_value("Job Applicant", onboarding.job_applicant, "email_id", "")
		with self.assertRaises(frappe.ValidationError) as raised:
			_send(onboarding.name)
		text = str(raised.exception)
		# A link to the Job Applicant, labelled with the applicant's name.
		self.assertIn(f"/job-applicant/{onboarding.job_applicant}", text)
		self.assertIn("Test Candidate</a> has no valid email address. Add one on the Job Applicant.", text)

	# M11: the button's read works while the Settings are incomplete.
	def test_the_state_is_readable_while_settings_are_incomplete(self):
		onboarding = self.make_onboarding()
		answer = _send(onboarding.name)
		frappe.db.set_value(REQUEST, answer["request"], "status", "Completed")
		frappe.db.set_single_value("Document Collection Settings", "portal_url", "")
		try:
			state = hr_api.get_onboarding_request(employee_onboarding=onboarding.name)
		finally:
			frappe.db.set_single_value("Document Collection Settings", "portal_url", PORTAL_URL)
		self.assertEqual(state["status"], "Completed")

	# M10: a disabled type is neither listed nor asked for.
	def test_a_disabled_document_type_is_not_asked_for(self):
		template = frappe.get_doc(service.TEMPLATE, install.DEFAULT_TEMPLATE)
		disabled = template.documents[-1].document_type
		frappe.db.set_value("Employee Document Type", disabled, "is_enabled", 0)
		try:
			onboarding = self.make_onboarding()
			answer = _send(onboarding.name)
			listed = [r.document_type for r in frappe.get_doc(REQUEST, answer["request"]).requested_documents]
			self.assertNotIn(disabled, listed)
			self.assertEqual(len(listed), len(template.documents) - 1)
			with self.assertRaises(frappe.ValidationError) as raised:
				template.save(ignore_permissions=True)
			self.assertIn("is disabled", str(raised.exception))
		finally:
			frappe.db.set_value("Employee Document Type", disabled, "is_enabled", 1)

	def test_dashboard_links_the_request(self):
		data = frappe.get_meta("Employee Onboarding").get_dashboard_data()
		items = [item for group in data.transactions for item in group["items"]]
		self.assertIn(REQUEST, items)
		self.assertEqual(data.non_standard_fieldnames[REQUEST], "employee_onboarding")

"""Cancelling or deleting an Employee Onboarding closes its request's link (T044, R18)."""

import frappe
from frappe.utils import getdate, today

from ninthsense.core.config import GENERIC_ERROR
from ninthsense.document_collection import service
from ninthsense.document_collection.tests.portal_harness import REQUEST, PortalTestCase, png_bytes


class TestLifecycle(PortalTestCase):
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

	def assert_delivery_refused(self, code=None):
		answer = self.deliver(self.completion(), code=code)
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))

	def test_cancelling_a_submitted_onboarding_cancels_its_request(self):
		self.submit(self.onboarding)
		self.assertEqual(self.request().status, "Link Sent")
		self.onboarding.reload()
		self.onboarding.cancel()
		self.commit()
		self.assertEqual(self.request().status, "Cancelled")
		self.assertEqual(self.request().employee_onboarding, self.onboarding.name)
		self.assert_delivery_refused()
		closed = self.get_request()
		self.assertEqual((closed.status, closed.message["state"]), (200, "revoked"))

	def test_deleting_a_draft_onboarding_cancels_and_unlinks_its_request(self):
		frappe.delete_doc("Employee Onboarding", self.onboarding.name)
		self.commit()
		self.assertFalse(frappe.db.exists("Employee Onboarding", self.onboarding.name))
		request = self.request()
		self.assertEqual(request.status, "Cancelled")
		self.assertFalse(request.employee_onboarding)
		self.assertEqual(request.onboarding_name, self.onboarding.name)
		self.assert_delivery_refused()

	def test_a_completed_request_stays_completed(self):
		self.submit(self.onboarding)
		frappe.db.set_value(REQUEST, self.request_name, "status", "Completed")
		self.onboarding.reload()
		self.onboarding.cancel()
		self.assertEqual(self.request().status, "Completed")

	def test_an_onboarding_without_a_request_is_untouched(self):
		other = self.make_onboarding()
		frappe.delete_doc("Employee Onboarding", other.name)
		self.assertFalse(frappe.db.exists("Employee Onboarding", other.name))
		self.assertIsNone(service.cancel_for_onboarding(other.name, deleted=False))

	def test_a_late_delivery_for_a_cancelled_request_after_it_delivered(self):
		# Data Received, then cancelled: a retry of the delivery is refused too.
		self.upload("aadhaar_front", png_bytes(), vdid="doc-1")
		payload = self.completion(codes=["aadhaar_front"])
		self.assertEqual(self.deliver(payload).status, 200)
		service.cancel_for_onboarding(self.onboarding.name, deleted=False)
		self.commit()
		answer = self.deliver(payload)
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))
		self.assertEqual(self.request().status, "Cancelled")
		self.assertTrue(self.request().verification_response)

	# M6: what the services write is not HR's to edit.
	def test_service_fields_are_read_only_and_refused_by_hand(self):
		meta = frappe.get_meta(REQUEST)
		for fieldname in ("verification_result", "job_applicant", "employee", "employee_onboarding"):
			self.assertTrue(meta.get_field(fieldname).read_only, fieldname)
		for table in ("requested_documents", "extractions", "fill_results"):
			self.assertTrue(meta.get_field(table).read_only, table)

		request = self.request()
		request.verification_result = "Passed"
		with self.assertRaises(frappe.ValidationError):
			request.save()
		request = self.request()
		request.job_applicant = self.make_onboarding().job_applicant
		with self.assertRaises(frappe.ValidationError):
			request.save()

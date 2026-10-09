import unittest

from ninthsense.core.reasons import ERROR_CODES, OnboardingError, guest_answer, hr_text

GENERIC = "This link is not valid."


class Reasons(unittest.TestCase):
	def test_every_code_has_hr_text_and_guest_answer(self):
		for code in ERROR_CODES:
			self.assertTrue(hr_text(code, setting="portal_url"), code)
			status, message = guest_answer(code)
			self.assertIsInstance(status, int, code)
			self.assertTrue(message, code)

	def test_signature_is_401(self):
		self.assertEqual(guest_answer("signature"), (401, GENERIC))

	def test_link_problems_are_generic_404(self):
		for code in ("link_invalid", "closed", "stale_ref"):
			self.assertEqual(guest_answer(code), (404, GENERIC))

	def test_schema_is_400(self):
		self.assertEqual(guest_answer("schema"), (400, GENERIC))

	def test_candidate_safe_texts_are_417(self):
		self.assertEqual(guest_answer("unknown_document"), (417, "Unknown document."))
		self.assertEqual(guest_answer("no_file"), (417, "No file was received."))
		self.assertEqual(guest_answer("file_size"), (417, "This file is too large."))
		self.assertEqual(guest_answer("file_type"), (417, "This file type is not accepted."))

	def test_hr_only_codes_stay_generic_to_guests(self):
		for code in (
			"not_configured",
			"no_email",
			"already_has_employee",
			"onboarding_cancelled",
			"template_required",
			"no_template",
			"no_documents",
		):
			self.assertEqual(guest_answer(code), (404, GENERIC))

	def test_not_configured_names_the_setting(self):
		self.assertIn("portal_url", hr_text("not_configured", setting="portal_url"))

	def test_closed_names_the_status(self):
		self.assertEqual(hr_text("closed", status="Completed"), "This request is closed (Completed).")

	def test_no_email_names_the_applicant_and_where_to_fix_it(self):
		self.assertEqual(
			hr_text("no_email", applicant="Asha Verma"),
			"Asha Verma has no valid email address. Add one on the Job Applicant.",
		)

	def test_template_refusals_say_what_to_do(self):
		self.assertEqual(hr_text("template_required"), "Pick an enabled document collection template.")
		self.assertEqual(hr_text("no_template"), "Create a document collection template first.")

	def test_translate_applies_to_the_template_before_the_context(self):
		self.assertEqual(
			hr_text("closed", translate=lambda text: text.replace("closed", "geschlossen"), status="closed"),
			"This request is geschlossen (closed).",
		)

	def test_error_carries_code_and_context(self):
		err = OnboardingError("no_email", "x", {"a": 1})
		self.assertEqual((err.code, err.message, err.context), ("no_email", "x", {"a": 1}))


if __name__ == "__main__":
	unittest.main()

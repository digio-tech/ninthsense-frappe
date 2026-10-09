"""The template mapping's guardrails (FR-042, FR-043, research R24)."""

import unittest

from ninthsense.core.field_catalogue import CATALOGUE
from ninthsense.core.mapping_rows import DEFAULT_MAPPING_ROWS
from ninthsense.core.mapping_rules import BLOCKED_SOURCES, allowed_sources, mapping_problems

STANDARD_CODES = {
	"aadhaar_front",
	"pan_card",
	"resume",
	"graduation_certificate",
	"cancelled_cheque",
	"latest_pay_slip",
	"bank_statement",
	"passport",
}


class BlockedSources(unittest.TestCase):
	def test_exactly_the_eight_new_job_pairs(self):
		self.assertEqual(
			BLOCKED_SOURCES,
			{
				(key, code)
				for key in ("designation", "department", "ctc", "date_of_joining")
				for code in ("offer_letter", "latest_pay_slip")
			},
		)
		self.assertEqual(len(BLOCKED_SOURCES), 8)


class AllowedSources(unittest.TestCase):
	def test_the_catalogue_codes_within_the_template_in_catalogue_order(self):
		template = {"aadhaar_front", "passport", "resume"}
		expected = tuple(code for code in CATALOGUE["first_name"].codes if code in template)
		self.assertEqual(allowed_sources("first_name", template), expected)
		self.assertEqual(expected, ("aadhaar_front", "passport", "resume"))

	def test_the_previous_job_never_supplies_the_new_one(self):
		for key in ("designation", "department", "ctc", "date_of_joining"):
			self.assertEqual(allowed_sources(key, {"offer_letter", "latest_pay_slip"}), (), key)

	def test_an_unknown_key_has_no_sources(self):
		self.assertEqual(allowed_sources("nope", STANDARD_CODES), ())


class MappingProblems(unittest.TestCase):
	def assert_one_problem(self, rows, codes, *parts):
		(problem,) = mapping_problems(rows, codes)
		for part in parts:
			self.assertIn(part, problem)

	def test_valid_rows_have_no_problem(self):
		self.assertEqual(mapping_problems(DEFAULT_MAPPING_ROWS, STANDARD_CODES), [])
		self.assertEqual(mapping_problems([], STANDARD_CODES), [])

	def test_an_unknown_key(self):
		self.assert_one_problem([("shoe_size", "resume", None)], STANDARD_CODES, "shoe_size")

	def test_a_duplicate_key(self):
		rows = [("pan_number", "pan_card", None), ("pan_number", "latest_pay_slip", None)]
		self.assert_one_problem(rows, STANDARD_CODES, "pan_number", "more than once")

	def test_a_source_outside_the_template(self):
		self.assert_one_problem(
			[("passport_number", "passport", None)], {"resume"}, "passport_number", "not one of the documents"
		)

	def test_a_source_the_catalogue_does_not_list(self):
		self.assert_one_problem(
			[("micr_code", "resume", None)], STANDARD_CODES, "micr_code", "cannot supply this field"
		)

	def test_a_blocked_pair(self):
		self.assert_one_problem(
			[("designation", "offer_letter", None)], {"offer_letter"}, "designation", "previous job"
		)

	def test_a_fallback_that_is_not_allowed(self):
		self.assert_one_problem(
			[("micr_code", "cancelled_cheque", "resume")], STANDARD_CODES, "micr_code", "fallback"
		)

	def test_a_fallback_outside_the_template(self):
		self.assert_one_problem(
			[("first_name", "aadhaar_front", "passport")], {"aadhaar_front"}, "first_name", "fallback"
		)

	def test_a_fallback_equal_to_the_source(self):
		self.assert_one_problem(
			[("ifsc_code", "cancelled_cheque", "cancelled_cheque")], STANDARD_CODES, "ifsc_code", "differ"
		)

	def test_a_missing_source(self):
		self.assert_one_problem([("pan_number", None, None)], STANDARD_CODES, "pan_number", "source")

	def test_every_problem_is_listed(self):
		rows = [
			("shoe_size", "resume", None),
			("designation", "latest_pay_slip", None),
			("ifsc_code", "cancelled_cheque", "cancelled_cheque"),
		]
		self.assertEqual(len(mapping_problems(rows, STANDARD_CODES)), 3)

	def test_translate_applies_to_each_message_before_it_is_filled(self):
		(problem,) = mapping_problems(
			[("pan_number", None, None)],
			STANDARD_CODES,
			translate=lambda text: text.replace("pick", "choose"),
		)
		self.assertIn("choose a source document", problem)
		self.assertIn("(pan_number)", problem)

	def test_labels_name_the_documents(self):
		(problem,) = mapping_problems(
			[("passport_number", "passport", None)], {"resume"}, labels={"passport": "Passport"}
		)
		self.assertIn("source Passport is not", problem)


if __name__ == "__main__":
	unittest.main()

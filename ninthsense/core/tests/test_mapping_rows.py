"""DEFAULT_MAPPING_ROWS is research R5's table, and every row is one the catalogue can serve."""

import unittest

from ninthsense.core.field_catalogue import CATALOGUE
from ninthsense.core.mapping_rows import DEFAULT_MAPPING_ROWS

R5 = (
	("first_name", "aadhaar_front", "pan_card"),
	("middle_name", "aadhaar_front", "pan_card"),
	("last_name", "aadhaar_front", "pan_card"),
	("gender", "aadhaar_front", None),
	("aadhaar_number", "aadhaar_front", None),
	("date_of_birth", "aadhaar_front", "pan_card"),
	("pan_number", "pan_card", None),
	("current_address", "resume", None),
	("permanent_address", "resume", None),
	("cell_number", "resume", None),
	("personal_email", "resume", None),
	("provident_fund_account", "latest_pay_slip", None),
	("education.school_univ", "graduation_certificate", None),
	("education.qualification", "graduation_certificate", None),
	("education.year_of_passing", "graduation_certificate", None),
	("education.class_per", "graduation_certificate", None),
	("external_work_history.company_name", "resume", None),
	("external_work_history.designation", "resume", None),
	("external_work_history.total_experience", "resume", None),
	("bank_name", "cancelled_cheque", "bank_statement"),
	("bank_ac_no", "cancelled_cheque", "bank_statement"),
	("ifsc_code", "cancelled_cheque", "bank_statement"),
	("micr_code", "cancelled_cheque", None),
	("passport_number", "passport", None),
	("date_of_issue", "passport", None),
	("valid_upto", "passport", None),
	("place_of_issue", "passport", None),
)


class MappingRows(unittest.TestCase):
	def test_rows_are_research_r5_in_order(self):
		self.assertEqual(DEFAULT_MAPPING_ROWS, R5)

	def test_every_key_is_in_the_catalogue(self):
		for key, _primary, _fallback in DEFAULT_MAPPING_ROWS:
			self.assertIn(key, CATALOGUE, key)

	def test_every_code_is_one_the_catalogue_lists_for_the_key(self):
		for key, primary, fallback in DEFAULT_MAPPING_ROWS:
			codes = CATALOGUE[key].codes
			self.assertIn(primary, codes, key)
			if fallback is not None:
				self.assertIn(fallback, codes, key)

	def test_no_row_reads_the_previous_offer_letter(self):
		for row in DEFAULT_MAPPING_ROWS:
			self.assertNotIn("offer_letter", row[1:], row[0])

	def test_no_row_fills_the_new_job(self):
		keys = {key for key, _primary, _fallback in DEFAULT_MAPPING_ROWS}
		self.assertFalse(keys & {"designation", "department", "ctc", "date_of_joining"})

	def test_a_key_appears_once(self):
		keys = [key for key, _primary, _fallback in DEFAULT_MAPPING_ROWS]
		self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
	unittest.main()

"""field_catalogue: the fixed list of fillable fields, and the one resolver both
extraction paths use. Frappe-free."""

import unittest

from ninthsense.core.field_catalogue import (
	CATALOGUE,
	ENTRIES,
	SECTIONS,
	TRANSFORM_DROPPED,
	get_entry,
	resolve,
)
from ninthsense.core.mapping import NO_EXTRACTION, NO_PATHS, NOT_PRESENT
from ninthsense.core.transforms import TRANSFORMS


class CatalogueShape(unittest.TestCase):
	def test_keys_are_unique(self):
		self.assertEqual(len(CATALOGUE), len(ENTRIES))

	def test_every_section_is_one_the_form_shows(self):
		for entry in ENTRIES:
			self.assertIn(entry.section, SECTIONS, entry.key)

	def test_every_transform_exists(self):
		for entry in ENTRIES:
			if entry.transform:
				self.assertIn(entry.transform, TRANSFORMS, entry.key)

	def test_only_employee_is_a_target(self):
		self.assertEqual({e.target_doctype for e in ENTRIES}, {"Employee"})

	def test_every_entry_has_a_source(self):
		for entry in ENTRIES:
			self.assertTrue(entry.sources, entry.key)
			for code, paths in entry.sources:
				self.assertTrue(paths, f"{entry.key} from {code}")

	def test_a_document_is_listed_once_per_entry(self):
		for entry in ENTRIES:
			self.assertEqual(len(entry.codes), len(set(entry.codes)), entry.key)

	def test_child_entries_name_their_table_and_row(self):
		for entry in ENTRIES:
			if entry.target_child_table:
				self.assertTrue(entry.target_row_key, entry.key)
				self.assertEqual(entry.key, f"{entry.target_child_table}.{entry.target_field}")
				self.assertEqual(entry.target_doctype, "Employee")

	def test_plain_entries_are_keyed_by_their_fieldname(self):
		for entry in ENTRIES:
			if not entry.target_child_table:
				self.assertEqual(entry.key, entry.target_field)

	def test_get_entry_tolerates_blanks_and_whitespace(self):
		self.assertIsNone(get_entry(None))
		self.assertIsNone(get_entry("nope"))
		self.assertIs(get_entry(" pan_number "), CATALOGUE["pan_number"])


class Sources(unittest.TestCase):
	def test_a_masters_certificate_supplies_every_field_a_graduation_one_does(self):
		for entry in ENTRIES:
			if "graduation_certificate" in entry.codes:
				self.assertEqual(
					entry.paths_for("masters_certificate"),
					entry.paths_for("graduation_certificate"),
					entry.key,
				)

	def test_an_experience_letter_fills_the_previous_employment_row(self):
		keys = {e.key for e in ENTRIES if "experience_letter" in e.codes}
		self.assertEqual(
			keys,
			{
				"external_work_history.company_name",
				"external_work_history.designation",
				"external_work_history.salary",
			},
		)

	def test_the_resume_can_stand_in_for_date_of_birth_and_education(self):
		for key in (
			"date_of_birth",
			"education.qualification",
			"education.school_univ",
			"education.year_of_passing",
		):
			self.assertIn("resume", CATALOGUE[key].codes, key)

	def test_a_resume_is_never_preferred_over_the_document_that_proves_it(self):
		# The dropdown lists sources in this order, so the certificate comes first.
		for key in ("date_of_birth", "education.qualification"):
			codes = CATALOGUE[key].codes
			self.assertEqual(codes[-1], "resume", key)


class Resolve(unittest.TestCase):
	def test_source_wins(self):
		result = resolve(
			CATALOGUE["pan_number"],
			[
				("Source", "PAN Card", "pan_card", {"pan_number": "AAAPR1234K"}),
				("Fallback", "Latest Pay Slip", "latest_pay_slip", {"pan_number": "ZZZZZ9999Z"}),
			],
		)
		self.assertEqual((result.value, result.document, result.role), ("AAAPR1234K", "PAN Card", "Source"))
		self.assertEqual(result.path, "pan_number")

	def test_fallback_is_tried_when_the_source_has_nothing(self):
		result = resolve(
			CATALOGUE["pan_number"],
			[
				("Source", "PAN Card", "pan_card", None),
				("Fallback", "Latest Pay Slip", "latest_pay_slip", {"pan_number": "ZZZZZ9999Z"}),
			],
		)
		self.assertEqual(
			(result.value, result.document, result.role), ("ZZZZZ9999Z", "Latest Pay Slip", "Fallback")
		)
		self.assertEqual(result.reasons, [("PAN Card", NO_EXTRACTION)])

	def test_the_entry_transform_is_applied(self):
		result = resolve(
			CATALOGUE["first_name"],
			[("Source", "Aadhaar Card Front", "aadhaar_front", {"name": "Vilas Rakhe"})],
		)
		self.assertEqual(result.value, "Vilas")
		self.assertEqual(result.raw, "Vilas Rakhe")

	def test_a_value_its_transform_drops_falls_through(self):
		result = resolve(
			CATALOGUE["middle_name"],
			[
				("Source", "Aadhaar Card Front", "aadhaar_front", {"name": "Vilas Rakhe"}),
				("Fallback", "PAN Card", "pan_card", {"name": "Vilas Kumar Rakhe"}),
			],
		)
		self.assertEqual((result.value, result.role), ("Kumar", "Fallback"))
		self.assertEqual(result.reasons, [("Aadhaar Card Front", TRANSFORM_DROPPED)])
		# Found on both, so both keys count as mapped even though the first was dropped.
		self.assertEqual(result.claimed, [("Aadhaar Card Front", "name"), ("PAN Card", "name")])

	def test_a_document_that_cannot_supply_the_field(self):
		result = resolve(CATALOGUE["pan_number"], [("Source", "Resume", "resume", {"pan_number": "X"})])
		self.assertIsNone(result.value)
		self.assertEqual(result.reasons, [("Resume", NO_PATHS)])
		self.assertEqual((result.document, result.role), ("Resume", "Source"))

	def test_nothing_found_anywhere(self):
		result = resolve(CATALOGUE["pan_number"], [("Source", "PAN Card", "pan_card", {"name": "Vilas"})])
		self.assertIsNone(result.value)
		self.assertEqual(result.reasons, [("PAN Card", NOT_PRESENT)])
		self.assertEqual(result.claimed, [])

	def test_no_attempts(self):
		result = resolve(CATALOGUE["pan_number"], [])
		self.assertIsNone(result.value)
		self.assertIsNone(result.document)

	def test_child_entry_reads_its_own_key(self):
		result = resolve(
			CATALOGUE["education.year_of_passing"],
			[("Source", "Graduation Certificate", "graduation_certificate", {"year_of_passing": "May 2017"})],
		)
		self.assertEqual(result.value, 2017)

	def test_the_resume_highest_qualification_year_is_shaped_too(self):
		result = resolve(
			CATALOGUE["education.year_of_passing"],
			[
				("Source", "Graduation Certificate", "graduation_certificate", None),
				("Fallback", "Resume", "resume", {"highest_qualification_year": "2017"}),
			],
		)
		self.assertEqual((result.value, result.role), (2017, "Fallback"))


if __name__ == "__main__":
	unittest.main()

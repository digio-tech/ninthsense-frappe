"""Unit tests for named value transforms.

env/bin/python -m unittest ninthsense.core.tests.test_transforms -v
"""

import unittest

from ninthsense.core.transforms import apply_transform


class ApplyTransform(unittest.TestCase):
	def test_no_transform_passes_the_value_through(self):
		for name in (None, "", "   "):
			self.assertEqual(apply_transform("ASHA MENON", name, "first_name"), "ASHA MENON")

	def test_an_unknown_transform_passes_the_value_through(self):
		self.assertEqual(apply_transform("ASHA MENON", "Nonsense", "first_name"), "ASHA MENON")

	def test_name_part_splits_a_single_string(self):
		self.assertEqual(apply_transform("ASHA R MENON", "Name Part", "first_name"), "Asha")
		self.assertEqual(apply_transform("ASHA R MENON", "Name Part", "middle_name"), "R")
		self.assertEqual(apply_transform("ASHA R MENON", "Name Part", "last_name"), "Menon")

	def test_name_part_handles_a_two_word_name(self):
		self.assertEqual(apply_transform("Asha Menon", "Name Part", "first_name"), "Asha")
		self.assertIsNone(apply_transform("Asha Menon", "Name Part", "middle_name"))
		self.assertEqual(apply_transform("Asha Menon", "Name Part", "last_name"), "Menon")

	def test_a_surname_is_the_last_name_whole(self):
		self.assertEqual(apply_transform("Verma", "Name Part", "last_name", "surname"), "Verma")
		self.assertEqual(apply_transform("SEN VERMA", "Name Part", "last_name", "surname"), "Sen Verma")
		self.assertIsNone(apply_transform("Sen Verma", "Name Part", "first_name", "surname"))
		self.assertIsNone(apply_transform("Sen Verma", "Name Part", "middle_name", "surname"))

	def test_a_given_name_gives_the_first_and_middle_names(self):
		self.assertEqual(apply_transform("Asha Kumari", "Name Part", "first_name", "given_name"), "Asha")
		self.assertEqual(apply_transform("Asha Kumari", "Name Part", "middle_name", "given_name"), "Kumari")
		self.assertIsNone(apply_transform("Asha", "Name Part", "middle_name", "given_name"))
		self.assertIsNone(apply_transform("Asha Kumari", "Name Part", "last_name", "given_name"))

	def test_a_full_name_key_is_split(self):
		self.assertEqual(apply_transform("Asha Verma", "Name Part", "last_name", "name"), "Verma")
		self.assertIsNone(apply_transform("Asha", "Name Part", "last_name", "full_name"))

	def test_name_part_rejects_something_that_looks_like_an_address(self):
		# An Aadhaar back side sometimes hands its address back as the name.
		self.assertIsNone(apply_transform("12/3, MG Road, Bengaluru", "Name Part", "first_name"))

	def test_compose_address_joins_a_block(self):
		block = {"line1": "12 MG Road", "city": "Bengaluru", "pincode": "560001"}
		self.assertEqual(
			apply_transform(block, "Compose Address", "current_address"),
			"12 MG Road, Bengaluru, 560001",
		)

	def test_compose_address_passes_a_plain_string_through(self):
		self.assertEqual(
			apply_transform("12 MG Road, Bengaluru", "Compose Address", "current_address"),
			"12 MG Road, Bengaluru",
		)

	def test_compose_address_prefers_a_pre_composed_full_string(self):
		block = {"full": "12 MG Road, Bengaluru - 560001", "line1": "ignored", "city": "ignored"}
		self.assertEqual(
			apply_transform(block, "Compose Address", "current_address"),
			"12 MG Road, Bengaluru - 560001",
		)

	def test_compose_address_accepts_pin_or_zip_as_a_pincode_alias(self):
		self.assertEqual(
			apply_transform({"city": "Bengaluru", "pin": "560001"}, "Compose Address", "x"),
			"Bengaluru, 560001",
		)
		self.assertEqual(
			apply_transform({"city": "Bengaluru", "zip": "560001"}, "Compose Address", "x"),
			"Bengaluru, 560001",
		)

	def test_title_case(self):
		self.assertEqual(apply_transform("ASHA MENON", "Title Case", "x"), "Asha Menon")

	def test_gender_turns_a_code_into_a_gender_record(self):
		self.assertEqual(apply_transform("M", "Gender", "gender"), "Male")
		self.assertEqual(apply_transform("female", "Gender", "gender"), "Female")
		self.assertEqual(apply_transform("MALE", "Gender", "gender"), "Male")
		self.assertIsNone(apply_transform("  ", "Gender", "gender"))

	def test_year_takes_the_year_out_of_a_date_ish_value(self):
		self.assertEqual(apply_transform("May 2017", "Year", "year_of_passing"), 2017)
		self.assertEqual(apply_transform("2017-05-30", "Year", "year_of_passing"), 2017)
		self.assertEqual(apply_transform(2017, "Year", "year_of_passing"), 2017)
		self.assertIsNone(apply_transform("Batch of 17", "Year", "year_of_passing"))

	def test_a_none_value_survives_every_transform(self):
		for name in ("Name Part", "Compose Address", "Title Case"):
			self.assertIsNone(apply_transform(None, name, "first_name"), msg=name)


if __name__ == "__main__":
	unittest.main()

"""Unit tests for mapping resolution.

Frappe-free, like the module it covers:

	env/bin/python -m unittest ninthsense.core.tests.test_mapping -v
"""

import unittest

from ninthsense.core.mapping import (
	NO_EXTRACTION,
	NO_PATHS,
	NOT_PRESENT,
	NULLISH,
	clean_value,
	dig,
	first_value,
	resolve_value,
)

EXTRACTED = {
	"pan_number": "ABCDE1234F",
	"name": "ASHA R MENON",
	"blank": "   ",
	"placeholder": "not visible",
	"bank": {"ifsc": "HDFC0001234", "account_number": "50100123456789"},
}


class Dig(unittest.TestCase):
	def test_reads_a_top_level_key(self):
		self.assertEqual(dig(EXTRACTED, "pan_number"), "ABCDE1234F")

	def test_follows_a_dotted_path(self):
		self.assertEqual(dig(EXTRACTED, "bank.ifsc"), "HDFC0001234")

	def test_returns_none_when_a_hop_is_missing(self):
		for path in ("nope", "bank.nope", "pan_number.nope", "a.b.c"):
			self.assertIsNone(dig(EXTRACTED, path), msg=path)


class CleanValue(unittest.TestCase):
	def test_passes_a_real_value_through(self):
		self.assertEqual(clean_value("ABCDE1234F"), "ABCDE1234F")

	def test_turns_provider_placeholders_into_none(self):
		for value in ("not visible", "NOT VISIBLE", "null", "N/A", "  none  ", "not available"):
			self.assertIsNone(clean_value(value), msg=value)

	def test_leaves_non_strings_alone(self):
		self.assertEqual(clean_value(42), 42)
		self.assertIsNone(clean_value(None))

	def test_the_placeholder_set_is_pinned(self):
		# Pinned deliberately: a member added or dropped by accident changes what
		# reaches a record.
		self.assertEqual(
			NULLISH,
			frozenset({"", "null", "none", "n/a", "na", "not visible", "not available", "-"}),
		)


class FirstValue(unittest.TestCase):
	def test_returns_the_first_path_that_holds_a_value(self):
		self.assertEqual(first_value(EXTRACTED, ("nope", "pan_number")), ("ABCDE1234F", "pan_number"))

	def test_skips_blank_and_placeholder_values(self):
		self.assertEqual(first_value(EXTRACTED, ("blank", "placeholder", "name")), ("ASHA R MENON", "name"))

	def test_returns_none_when_nothing_matches(self):
		self.assertEqual(first_value(EXTRACTED, ("nope", "also_nope")), (None, None))


class ResolveValue(unittest.TestCase):
	def test_resolves_through_the_first_path_that_holds_a_value(self):
		self.assertEqual(
			resolve_value(EXTRACTED, ("nope", "pan_number")),
			("ABCDE1234F", "pan_number", None),
		)

	def test_resolves_a_dotted_path(self):
		self.assertEqual(
			resolve_value(EXTRACTED, ("bank.account_number",)),
			("50100123456789", "bank.account_number", None),
		)

	def test_reports_when_no_path_holds_a_value(self):
		self.assertEqual(resolve_value(EXTRACTED, ("nope",)), (None, None, NOT_PRESENT))

	def test_reports_when_there_is_nothing_to_read_from(self):
		self.assertEqual(resolve_value(None, ("pan_number",)), (None, None, NO_EXTRACTION))

	def test_reports_when_no_path_is_configured_at_all(self):
		self.assertEqual(resolve_value(EXTRACTED, None), (None, None, NO_PATHS))

	def test_no_paths_is_reported_before_a_missing_extraction(self):
		self.assertEqual(resolve_value(None, None), (None, None, NO_PATHS))


if __name__ == "__main__":
	unittest.main()

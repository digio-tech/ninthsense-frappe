"""Unit tests for Aadhaar masking.

	cd apps/ninthsense && ../../env/bin/python -m unittest \
		ninthsense.core.tests.test_masking -v
"""

import unittest

from ninthsense.core.masking import (
	UNREADABLE,
	is_aadhaar_key,
	mask_aadhaar,
	mask_payload,
	mask_text,
)


class MaskAadhaar(unittest.TestCase):
	def test_twelve_digits_keep_only_the_last_four(self):
		for raw in ("773008892163", "7730 0889 2163", "7730-0889-2163", 773008892163):
			self.assertEqual(mask_aadhaar(raw), "XXXX XXXX 2163")

	def test_anything_else_is_replaced_outright(self):
		for raw in ("77300889216", "7730088921631", "ABCD 0889 2163", None, ["773008892163"], True):
			self.assertEqual(mask_aadhaar(raw), UNREADABLE)

	def test_a_masked_value_keeps_its_last_four(self):
		for raw in ("XXXX XXXX 2163", "XXXXXXXX2163", "xxxx-xxxx-2163", "********2163"):
			self.assertEqual(mask_aadhaar(raw), "XXXX XXXX 2163")


class AadhaarKey(unittest.TestCase):
	def test_number_fields_are_recognised(self):
		for key in ("aadhaar_number", "aadhaarNumber", "Aadhaar No", "aadhar_num", "uid"):
			self.assertTrue(is_aadhaar_key(key), key)

	def test_document_names_and_other_ids_are_not(self):
		for key in (
			"aadhaar",
			"aadhaar_front",
			"aadhaar_card_back",
			"uuid",
			"session_id",
			"document_uid_hint",
		):
			self.assertFalse(is_aadhaar_key(key), key)


class MaskText(unittest.TestCase):
	def test_runs_in_prose_are_masked(self):
		self.assertEqual(
			mask_text("Aadhaar 7730 0889 2163 matched the PAN holder."),
			"Aadhaar XXXX XXXX 2163 matched the PAN holder.",
		)

	def test_longer_numbers_are_left_alone(self):
		self.assertEqual(mask_text("Account 50100123456789"), "Account 50100123456789")


class MaskPayload(unittest.TestCase):
	def payload(self):
		return {
			"summary": "Aadhaar 773008892163 belongs to Vilas Rakhe.",
			"steps": [
				{
					"documents": [
						{
							"document_code": "aadhaar_front",
							"extracted": {
								"name": "Vilas Rakhe",
								"aadhaar_number": "7730 0889 2163",
								"date_of_birth": "1995-05-30",
							},
						},
						{
							"document_code": "cancelled_cheque",
							"extracted": {"account_number": "123456789012", "ifsc": "DEMO0001234"},
						},
					],
					"checks": [{"detail": {"uid": 773008892163}}],
					"extractions": {
						"aadhaar": {"name": "Vilas Rakhe", "aadhaar_number": "773008892163"},
						"cancelled_cheque": {"account_number": "123456789012"},
					},
				}
			],
		}

	def test_the_number_read_off_the_card_is_masked(self):
		masked = mask_payload(self.payload())
		front = masked["steps"][0]["documents"][0]["extracted"]
		self.assertEqual(front["aadhaar_number"], "XXXX XXXX 2163")
		self.assertEqual(front["name"], "Vilas Rakhe")
		self.assertEqual(front["date_of_birth"], "1995-05-30")

	def test_free_text_and_nested_keys_are_masked(self):
		masked = mask_payload(self.payload())
		self.assertEqual(masked["summary"], "Aadhaar XXXX XXXX 2163 belongs to Vilas Rakhe.")
		self.assertEqual(masked["steps"][0]["checks"][0]["detail"]["uid"], "XXXX XXXX 2163")

	def test_the_card_block_keeps_everything_but_the_number(self):
		card = mask_payload(self.payload())["steps"][0]["extractions"]["aadhaar"]
		self.assertEqual(card, {"name": "Vilas Rakhe", "aadhaar_number": "XXXX XXXX 2163"})

	def test_a_twelve_digit_bank_account_survives(self):
		step = mask_payload(self.payload())["steps"][0]
		self.assertEqual(step["documents"][1]["extracted"]["account_number"], "123456789012")
		self.assertEqual(step["extractions"]["cancelled_cheque"]["account_number"], "123456789012")

	def test_no_aadhaar_number_is_left_anywhere(self):
		masked = repr(mask_payload(self.payload())).replace("123456789012", "")
		self.assertNotRegex(masked, r"(?<!\d)\d(?:[ -]?\d){11}(?!\d)")

	def test_the_input_is_not_changed(self):
		payload = self.payload()
		mask_payload(payload)
		self.assertEqual(payload["steps"][0]["documents"][0]["extracted"]["aadhaar_number"], "7730 0889 2163")

	def test_a_block_that_is_not_an_object_is_scrubbed_by_shape(self):
		masked = mask_payload(
			{
				"documents": [
					{"document_code": "pan_card", "extracted": "UID 7730 0889 2163, PAN ABCDE1234F"}
				],
				"extractions": [{"id": "773008892163"}, "773008892163"],
			}
		)
		self.assertEqual(masked["documents"][0]["extracted"], "UID XXXX XXXX 2163, PAN ABCDE1234F")
		self.assertEqual(masked["extractions"], [{"id": "XXXX XXXX 2163"}, "XXXX XXXX 2163"])

	def test_an_aadhaar_card_is_scrubbed_by_shape_whatever_it_calls_the_number(self):
		masked = mask_payload(
			{
				"documents": [
					{"document_code": "aadhaar_back", "extracted": {"id_number": "7730 0889 2163"}},
					# Filed under PAN, recognised as an Aadhaar card.
					{
						"document_code": "pan_card",
						"detected_document_type": "aadhaar_front",
						"extracted": {"document_number": "773008892163", "name": "Vilas Rakhe"},
					},
				],
				"extractions": {"aadhaar": {"document_number": "773008892163"}},
			}
		)
		documents = masked["documents"]
		self.assertEqual(documents[0]["extracted"], {"id_number": "XXXX XXXX 2163"})
		self.assertEqual(
			documents[1]["extracted"], {"document_number": "XXXX XXXX 2163", "name": "Vilas Rakhe"}
		)
		self.assertEqual(masked["extractions"]["aadhaar"], {"document_number": "XXXX XXXX 2163"})

	def test_empty_values_stay_empty(self):
		self.assertEqual(mask_payload({"aadhaar_number": ""}), {"aadhaar_number": ""})
		self.assertEqual(mask_payload({"aadhaar_number": None}), {"aadhaar_number": None})


if __name__ == "__main__":
	unittest.main()

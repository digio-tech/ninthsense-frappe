import json
import unittest
from pathlib import Path

from ninthsense.core.extraction import document_step, extraction_rows, verification_result

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "completion-mock.json"


class ExtractionRows(unittest.TestCase):
	def test_flattens_skips_and_joins(self):
		step = {
			"documents": [
				{
					"document_code": "aadhaar_front",
					"extracted": {
						"name": "Asha Verma",
						"_debug": "dropped",
						"address": {"line1": "12 Sample Street", "city": "Bengaluru", "_raw": "x"},
						"languages": ["English", "Kannada"],
						"dob": "Not visible",
						"age": 30,
					},
				},
				{"document_code": "resume", "extracted": None},
				{"document_code": "pan_card", "extracted": "not a dict"},
			]
		}
		self.assertEqual(
			extraction_rows(step),
			[
				("aadhaar_front", "name", "Asha Verma"),
				("aadhaar_front", "address.line1", "12 Sample Street"),
				("aadhaar_front", "address.city", "Bengaluru"),
				("aadhaar_front", "languages", "English, Kannada"),
				("aadhaar_front", "dob", "Not visible"),
				("aadhaar_front", "age", "30"),
			],
		)

	def test_no_documents(self):
		self.assertEqual(extraction_rows({}), [])

	def test_fixture_has_rows_for_every_seeded_document(self):
		payload = json.loads(FIXTURE.read_text())
		codes = {code for code, _key, _value in extraction_rows(document_step(payload))}
		self.assertEqual(
			codes,
			{
				"aadhaar_front",
				"pan_card",
				"resume",
				"graduation_certificate",
				"cancelled_cheque",
				"latest_pay_slip",
				"bank_statement",
				"passport",
			},
		)


class VerificationResult(unittest.TestCase):
	def test_map(self):
		self.assertEqual(verification_result({"status": "completed"}), "Passed")
		self.assertEqual(verification_result({"status": "review"}), "Needs Review")
		self.assertEqual(verification_result({"status": "failed"}), "Failed")
		self.assertEqual(verification_result({"status": "other"}), "Needs Review")
		self.assertEqual(verification_result({}), "Needs Review")


class DocumentStep(unittest.TestCase):
	def test_prefers_the_document_collection_step(self):
		payload = {"steps": [{"id": "x", "type": "esign"}, {"id": "docs", "type": "document_collection"}]}
		self.assertEqual(document_step(payload)["id"], "docs")
		self.assertEqual(document_step({"steps": [{"id": "x", "type": "esign"}]})["id"], "x")
		self.assertEqual(document_step({}), {})


if __name__ == "__main__":
	unittest.main()

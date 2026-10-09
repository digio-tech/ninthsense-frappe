"""The vendored contract: digests, validation, and the recorded fixture."""

import json
import unittest
from pathlib import Path

from ninthsense.core.contract import validate
from ninthsense.core.reasons import OnboardingError

CONTRACT = Path(validate.__file__).resolve().parent
EXAMPLES = CONTRACT / "examples"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "completion-mock.json"


def _load(path):
	return json.loads(path.read_text())


class Digests(unittest.TestCase):
	def test_vendored_schemas_match_digests(self):
		expected = {}
		for line in (CONTRACT / "DIGESTS").read_text().splitlines():
			digest, name = line.split()
			expected[name] = digest
		self.assertEqual(set(expected), set(validate.SCHEMA_FILES))
		self.assertEqual(validate.schema_digests(), expected)


class Validation(unittest.TestCase):
	def test_request_examples(self):
		validate.validate_request(_load(EXAMPLES / "request-valid.json"))
		with self.assertRaises(OnboardingError) as raised:
			validate.validate_request(_load(EXAMPLES / "request-invalid.json"))
		self.assertEqual(raised.exception.code, "schema")

	def test_completion_examples(self):
		validate.validate_completion(_load(EXAMPLES / "completion-valid.json"))
		with self.assertRaises(OnboardingError) as raised:
			validate.validate_completion(_load(EXAMPLES / "completion-invalid.json"))
		self.assertEqual(raised.exception.code, "schema")
		self.assertEqual(raised.exception.context, {"pointer": "/ref"})

	def test_error_names_a_pointer_never_the_value(self):
		body = _load(EXAMPLES / "completion-valid.json")
		secret = "999988887777-not-a-status"
		body["status"] = secret
		with self.assertRaises(OnboardingError) as raised:
			validate.validate_completion(body)
		exc = raised.exception
		self.assertEqual(exc.context, {"pointer": "/status"})
		self.assertNotIn(secret, str(exc))
		self.assertNotIn(secret, repr(exc.context))

	def test_nested_pointer(self):
		body = _load(EXAMPLES / "completion-valid.json")
		del body["steps"][0]["documents"][1]["verification_document_id"]
		with self.assertRaises(OnboardingError) as raised:
			validate.validate_completion(body)
		self.assertEqual(raised.exception.context["pointer"], "/steps/0/documents/1/verification_document_id")

	def test_unsupported_version_is_refused(self):
		body = _load(EXAMPLES / "completion-valid.json")
		body["schema_version"] = "3.0"
		with self.assertRaises(OnboardingError) as raised:
			validate.validate_completion(body)
		self.assertEqual(raised.exception.context, {"pointer": "/schema_version"})

	def test_fixture_validates(self):
		validate.validate_completion(_load(FIXTURE))


if __name__ == "__main__":
	unittest.main()

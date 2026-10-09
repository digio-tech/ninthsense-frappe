import unittest

from ninthsense.core.config import CALLBACK_PATH
from ninthsense.core.contract.validate import validate_request
from ninthsense.core.descriptor import build_descriptor

ROW = {
	"idx": 1,
	"document_type": "Aadhaar Card Front",
	"document_code": "aadhaar_front",
	"is_mandatory": 1,
	"allowed_file_types": "pdf, JPEG,jpg,png,pdf",
	"max_file_size_mb": 3,
	"help_text": "h" * 500,
	"display_group": "g" * 80,
	"staged_verification_document_id": "doc-1",
}


def inputs(**overrides):
	base = {
		"ref": "DCR-2026-0001.abcdefghijklmnop",
		"instance": "https://hr.example.com",
		"state": "open",
		"expires_at": "2026-10-21T10:00:00+05:30",
		"org_name": "Digio India",
		"logo_url": "https://hr.example.com/files/logo.png",
		"accent_color": "#1a73e8",
		"support_email": "hr@example.com",
		"display_name": "A" * 200,
		"application": "DCR-2026-0001",
		"documents": [ROW, {"idx": 2, "document_type": "Resume", "document_code": "resume"}],
		"replaced_ids": ["doc-0"],
	}
	base.update(overrides)
	return base


class OpenDescriptor(unittest.TestCase):
	def setUp(self):
		self.d = build_descriptor(inputs())
		validate_request(self.d)

	def test_envelope(self):
		d = self.d
		self.assertEqual(d["ref"], "DCR-2026-0001.abcdefghijklmnop")
		self.assertEqual(d["goal_key"], "onboarding")
		self.assertEqual(d["stage"], "Onboarding")
		self.assertEqual(d["catalogue_version"], 1)
		self.assertEqual(d["completion"]["callback_path"], CALLBACK_PATH)
		self.assertEqual(d["hrms"], {"system": "frappe-hrms", "instance": "https://hr.example.com"})
		self.assertEqual(
			d["features"], {"allow_replace_before_submit": True, "on_classifier_disagreement": "warn"}
		)
		self.assertEqual(d["subject"]["display_name"], "A" * 120)
		self.assertEqual(d["x-hrms"], {"application": "DCR-2026-0001"})
		self.assertEqual(d["steps"][0]["id"], "docs")
		self.assertEqual(d["steps"][0]["replaced_verification_document_ids"], ["doc-0"])
		self.assertEqual(
			d["branding"],
			{
				"org_name": "Digio India",
				"logo_url": "https://hr.example.com/files/logo.png",
				"accent_color": "#1a73e8",
				"support_email": "hr@example.com",
			},
		)

	def test_documents(self):
		first, second = self.d["steps"][0]["documents"]
		self.assertEqual(first["max_bytes"], 3 * 1048576)
		self.assertEqual(first["accept"], [".pdf", ".jpeg", ".jpg", ".png"])
		self.assertEqual(first["help"], "h" * 400)
		self.assertEqual(first["group"], "g" * 60)
		self.assertEqual(first["verification_document_id"], "doc-1")
		self.assertEqual(first["label"], "Aadhaar Card Front")
		self.assertEqual((first["order"], first["mandatory"]), (1, True))
		self.assertNotIn("verification_document_id", second)
		self.assertNotIn("help", second)
		self.assertNotIn("group", second)


class ClosedDescriptor(unittest.TestCase):
	def test_non_open_has_nothing_to_collect(self):
		for state in ("submitted", "expired", "revoked"):
			d = build_descriptor(inputs(state=state))
			validate_request(d)
			self.assertEqual(d["state"], state)
			for key in ("subject", "features", "x-hrms"):
				self.assertNotIn(key, d)
			self.assertEqual(d["steps"][0]["documents"], [])
			self.assertNotIn("replaced_verification_document_ids", d["steps"][0])


class Branding(unittest.TestCase):
	def test_invalid_values_are_omitted(self):
		d = build_descriptor(
			inputs(accent_color="blue", support_email="hr.example.com", logo_url="/files/logo.png")
		)
		validate_request(d)
		self.assertEqual(d["branding"], {"org_name": "Digio India"})


if __name__ == "__main__":
	unittest.main()

import unittest

from ninthsense.core.log_fields import clean_fields, exception_site

ALLOWED = {
	"request",
	"onboarding",
	"employee",
	"portal_request_id",
	"status",
	"outcome",
	"category",
	"duration_ms",
	"count",
	"op",
	"pointer",
	"exception",
}


class CleanFields(unittest.TestCase):
	def test_keeps_allowed_scalars(self):
		fields = {k: 1 for k in ALLOWED}
		self.assertEqual(clean_fields(fields), fields)

	def test_drops_other_keys(self):
		fields = clean_fields(
			{"request": "DCR-1", "email": "a@b.in", "name": "Kavya", "value": "x", "payload": "y"}
		)
		self.assertEqual(fields, {"request": "DCR-1"})

	def test_drops_nested_values_under_allowed_keys(self):
		fields = clean_fields({"status": {"a": 1}, "outcome": ["x"], "count": 3})
		self.assertEqual(fields, {"count": 3})


def _fail(secret):
	raise ValueError(f"bad value {secret}")


class ExceptionSite(unittest.TestCase):
	def test_names_the_type_and_innermost_line_but_not_the_message(self):
		try:
			_fail("999988887777")
		except ValueError as exc:
			site = exception_site(exc, root=__file__.rsplit("/", 1)[0])
		self.assertTrue(site.startswith("ValueError at test_log_fields.py:"), site)
		self.assertNotIn("999988887777", site)

	def test_an_exception_never_raised_has_only_its_type(self):
		self.assertEqual(exception_site(KeyError("x")), "KeyError")


if __name__ == "__main__":
	unittest.main()

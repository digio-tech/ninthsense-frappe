"""Unit tests for the invite email's render context.

	../../env/bin/python -m unittest ninthsense.core.tests.test_invite_email -v

The shipped subject and body are read straight out of install.py rather than
copied here, so editing the template and forgetting the context is what fails.
"""

import re
import unittest
from pathlib import Path

from ninthsense.core.invite_email import (
	CONTEXT_KEYS,
	build_invite_context,
	template_keys,
)

# install.py imports click and frappe at module scope, neither of which is
# available in a bare unittest run. The two constants are plain string literals,
# so they are lifted out of the source instead of imported.
_SOURCE = (Path(__file__).resolve().parents[2] / "install.py").read_text()


def _literal(name: str) -> str:
	match = re.search(rf'^{name} = ("""(?P<block>.*?)"""|"(?P<line>[^"]*)")', _SOURCE, re.S | re.M)
	if not match:
		raise AssertionError(f"{name} not found in install.py")
	return match.group("block") or match.group("line")


SHIPPED_SUBJECT = _literal("INVITE_EMAIL_SUBJECT")
SHIPPED_BODY = _literal("INVITE_EMAIL_BODY")


def context(**kwargs):
	base = {
		"candidate_name": "Asha Menon",
		"company": "Digio India",
		"job_title": "Engineer",
		"document_count": 2,
		"link": "https://portal.example/s/demo/abc",
		"expires_on": "29-09-2026",
		"valid_days": 14,
	}
	base.update(kwargs)
	return build_invite_context(**base)


class TemplateKeys(unittest.TestCase):
	def test_it_finds_a_key_in_an_expression(self):
		self.assertEqual(template_keys("<p>{{ doc.candidate_name }}</p>"), {"candidate_name"})

	def test_it_finds_a_key_in_a_statement(self):
		self.assertEqual(template_keys("{% if doc.job_title -%}x{%- endif %}"), {"job_title"})

	def test_it_finds_a_key_behind_a_filter(self):
		self.assertEqual(template_keys("{{ doc.company|upper }}"), {"company"})

	def test_it_finds_every_key_in_one_source(self):
		self.assertEqual(template_keys("{{ doc.a }} {% if doc.b %}{{ doc.c }}{% endif %}"), {"a", "b", "c"})

	def test_it_finds_nothing_in_a_template_with_no_keys(self):
		self.assertEqual(template_keys("<p>Hello</p>"), set())

	def test_it_ignores_a_bare_word_ending_in_doc(self):
		self.assertEqual(template_keys("{{ mydoc.name }}"), set())

	def test_it_tolerates_an_empty_source(self):
		self.assertEqual(template_keys(""), set())
		self.assertEqual(template_keys(None), set())


class ShippedTemplateMatchesTheContext(unittest.TestCase):
	"""The whole point: a key the template reads that nothing supplies renders
	as an empty string, so only a test catches it."""

	def test_every_key_the_subject_reads_is_supplied(self):
		self.assertLessEqual(template_keys(SHIPPED_SUBJECT), CONTEXT_KEYS)

	def test_every_key_the_body_reads_is_supplied(self):
		self.assertLessEqual(template_keys(SHIPPED_BODY), CONTEXT_KEYS)

	def test_the_body_asks_for_the_four_values_hr_promised_candidates(self):
		keys = template_keys(SHIPPED_BODY)
		for required in ("candidate_name", "job_title", "link", "expires_on"):
			self.assertIn(required, keys)

	def test_the_context_supplies_exactly_the_declared_keys(self):
		self.assertEqual(set(context()), set(CONTEXT_KEYS))


class BuildInviteContext(unittest.TestCase):
	def test_it_passes_values_through(self):
		self.assertEqual(context()["candidate_name"], "Asha Menon")
		self.assertEqual(context()["expires_on"], "29-09-2026")
		self.assertEqual(context()["document_count"], 2)

	def test_a_missing_job_title_is_blank_not_absent(self):
		for missing in (None, "", "   "):
			result = context(job_title=missing)
			self.assertIn("job_title", result)
			self.assertEqual(result["job_title"], "")

	def test_a_blank_job_title_drops_the_role_line_rather_than_printing_an_empty_one(self):
		import jinja2

		rendered = jinja2.Template(SHIPPED_BODY).render(doc=context(job_title=None))
		self.assertNotIn("Role:", rendered)

	def test_a_job_title_is_printed_when_there_is_one(self):
		import jinja2

		rendered = jinja2.Template(SHIPPED_BODY).render(doc=context())
		self.assertIn("Role:", rendered)
		self.assertIn("Engineer", rendered)

	def test_the_expiry_date_reaches_the_rendered_body(self):
		import jinja2

		rendered = jinja2.Template(SHIPPED_BODY).render(doc=context())
		self.assertIn("29-09-2026", rendered)
		self.assertIn("14 days", rendered)

	def test_a_missing_expiry_drops_the_until_clause_but_keeps_the_duration(self):
		import jinja2

		rendered = jinja2.Template(SHIPPED_BODY).render(doc=context(expires_on=None))
		self.assertNotIn("until", rendered)
		self.assertIn("14 days", rendered)

	def test_the_link_is_rendered_verbatim(self):
		import jinja2

		rendered = jinja2.Template(SHIPPED_BODY).render(doc=context())
		self.assertIn("https://portal.example/s/demo/abc", rendered)

	def test_surrounding_whitespace_is_stripped(self):
		self.assertEqual(context(candidate_name="  Asha  ")["candidate_name"], "Asha")
		self.assertEqual(context(company=" Digio ")["company"], "Digio")

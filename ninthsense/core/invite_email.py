"""The context the document-request invite email is rendered with.

Frappe-free. The key set here is the contract between the send path and the
`Document Request Link` Email Template, and Jinja renders an unknown key as
nothing rather than raising -- so a template asking for `doc.designation` when
the context supplies `job_title` produces a letter with a hole in it and no
error anywhere. `template_keys()` exists so that drift is a failing test instead
of something a candidate notices first.
"""

import re

# Every key the invite template may name. A key added here has to be produced by
# build_invite_context() too, which test_invite_email asserts.
CONTEXT_KEYS = frozenset(
	{
		"candidate_name",
		"company",
		"job_title",
		"document_count",
		"link",
		"expires_on",
		"valid_days",
	}
)

# `{{ doc.foo }}`, `{%- if doc.foo -%}`, `doc.foo|title` -- the name after `doc.`
# wherever it appears inside a Jinja delimiter.
_DOC_KEY = re.compile(r"\bdoc\.([a-zA-Z_][a-zA-Z0-9_]*)")


def template_keys(source: str) -> set[str]:
	"""Every `doc.<key>` an Email Template's subject or body reads."""
	return set(_DOC_KEY.findall(source or ""))


def build_invite_context(
	*,
	candidate_name: str | None,
	company: str | None,
	job_title: str | None,
	document_count: int,
	link: str,
	expires_on: str | None,
	valid_days: int,
) -> dict:
	"""The render context for one invite.

	Blank-but-present rather than absent: `job_title` is the one value that is
	routinely missing (a Job Applicant created without a Designation), and the
	template guards on it being falsy. Leaving the key out entirely would work
	the same way in Jinja but would hide the difference between "this candidate
	has no title yet" and "the send path forgot to pass one".

	`expires_on` is a formatted date, not a datetime: the caller formats it in
	the site's date format, because a candidate reading "29-09-2026" should not
	have to parse a timestamp. `valid_days` stays alongside it -- the two say
	different things ("for 14 days" and "until the 29th") and the template uses
	both.
	"""
	return {
		"candidate_name": (candidate_name or "").strip(),
		"company": (company or "").strip(),
		"job_title": (job_title or "").strip(),
		"document_count": document_count,
		"link": link,
		"expires_on": (expires_on or "").strip(),
		"valid_days": valid_days,
	}

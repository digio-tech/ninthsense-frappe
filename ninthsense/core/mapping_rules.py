"""What a template's field mapping may say (FR-042, FR-043, research R24). Frappe-free.

The catalogue lists every document that can carry a field. A template may read a field only
from its own documents, and never the new job's terms from the previous job's papers: the
previous employer's offer letter and pay slip describe the old job, so they never fill
designation, department, CTC or joining date. The editor's options and the template's
`validate` both come from here.
"""

from ninthsense.core.field_catalogue import get_entry
from ninthsense.core.reasons import _

#: The new job's terms, and the documents that describe the previous one.
NEW_JOB_FIELDS = ("designation", "department", "ctc", "date_of_joining")
PREVIOUS_JOB_DOCUMENTS = ("offer_letter", "latest_pay_slip")

BLOCKED_SOURCES = frozenset((key, code) for key in NEW_JOB_FIELDS for code in PREVIOUS_JOB_DOCUMENTS)


def allowed_sources(key: str, template_codes) -> tuple[str, ...]:
	"""The template's document codes that can supply `key`, in catalogue order, never a blocked pair."""
	entry = get_entry(key)
	if entry is None:
		return ()
	codes = set(template_codes or ())
	return tuple(code for code in entry.codes if code in codes and (entry.key, code) not in BLOCKED_SOURCES)


# Why a document cannot supply a field, by role. `{field}` names the field, `{document}` the document.
_PROBLEMS = {
	("source", "outside"): _(
		"{field}: source {document} is not one of the documents this template asks for."
	),
	("source", "previous_job"): _(
		"{field}: source {document} describes the previous job, so it never fills this field."
	),
	("source", "unsupported"): _("{field}: source {document} cannot supply this field."),
	("fallback", "outside"): _(
		"{field}: fallback {document} is not one of the documents this template asks for."
	),
	("fallback", "previous_job"): _(
		"{field}: fallback {document} describes the previous job, so it never fills this field."
	),
	("fallback", "unsupported"): _("{field}: fallback {document} cannot supply this field."),
}
_UNKNOWN_KEY = _("{key}: not a field the app can fill.")
_DUPLICATE = _("{field} is mapped more than once.")
_NO_SOURCE = _("{field}: pick a source document.")
_SAME_FALLBACK = _("{field}: the fallback must differ from the source.")


def _document_problem(key: str, code: str, template_codes: set) -> str | None:
	if code not in template_codes:
		return "outside"
	if (key, code) in BLOCKED_SOURCES:
		return "previous_job"
	if code not in get_entry(key).codes:
		return "unsupported"
	return None


def mapping_problems(rows, template_codes, labels: dict | None = None, translate=None) -> list[str]:
	"""Every problem with `rows`, as `(field_key, source_code, fallback_code_or_None)`; [] when none.

	Each problem names the field key. `labels` maps a document code to the name shown in the
	message; a code without one is shown as is. `translate` (frappe._ at the edge) is applied to
	each message before it is filled in.
	"""
	template_codes = set(template_codes or ())
	labels = labels or {}
	tr = translate or (lambda text: text)
	problems: list[str] = []
	seen: set = set()

	for key, source, fallback in rows or ():
		entry = get_entry(key)
		if entry is None:
			problems.append(tr(_UNKNOWN_KEY).format(key=key))
			continue
		field = f"{entry.label} ({entry.key})"
		if entry.key in seen:
			problems.append(tr(_DUPLICATE).format(field=field))
			continue
		seen.add(entry.key)

		if not source:
			problems.append(tr(_NO_SOURCE).format(field=field))
		else:
			problem = _document_problem(entry.key, source, template_codes)
			if problem:
				message = tr(_PROBLEMS["source", problem])
				problems.append(message.format(field=field, document=labels.get(source, source)))

		if not fallback:
			continue
		if fallback == source:
			problems.append(tr(_SAME_FALLBACK).format(field=field))
			continue
		problem = _document_problem(entry.key, fallback, template_codes)
		if problem:
			message = tr(_PROBLEMS["fallback", problem])
			problems.append(message.format(field=field, document=labels.get(fallback, fallback)))

	return problems

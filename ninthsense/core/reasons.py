"""Every failure has a shape: one error class, enumerated codes, one mapper (R-IX).

`hr_text` is what HR sees, translated at the edge. `guest_answer` is what the portal gets: a generic answer
for everything except the few candidate-safe messages, which are answered with 417.
"""

from ninthsense.core.config import GENERIC_ERROR

ERROR_CODES = (
	"not_configured",
	"no_email",
	"closed",
	"link_invalid",
	"signature",
	"stale_ref",
	"schema",
	"file_type",
	"file_size",
	"no_file",
	"unknown_document",
	"already_has_employee",
	"onboarding_cancelled",
	"template_required",
	"no_template",
	"no_documents",
)


def _(text: str) -> str:
	"""Marks `text` for Frappe's translation extractor, which collects every `_("...")` literal.

	core/ never imports frappe, so the edge translates: `hr_text(code, translate=frappe._)`.
	"""
	return text


class OnboardingError(Exception):
	def __init__(self, code: str, message: str = "", context: dict | None = None):
		super().__init__(message or code)
		self.code = code
		self.message = message
		self.context = context or {}


_HR_TEXT = {
	"not_configured": _("Document Collection Settings is incomplete: {setting}."),
	"no_email": _("{applicant} has no valid email address. Add one on the Job Applicant."),
	"closed": _("This request is closed ({status})."),
	"link_invalid": _("The link is not valid."),
	"signature": _("The portal's callback signature did not verify."),
	"stale_ref": _("The portal's reference does not match the current link."),
	"schema": _("The portal's answer did not match the expected shape."),
	"file_type": _("This file type is not accepted."),
	"file_size": _("This file is too large."),
	"no_file": _("No file was received."),
	"unknown_document": _("Unknown document."),
	"already_has_employee": _("This onboarding already has an Employee."),
	"onboarding_cancelled": _("The Employee Onboarding was cancelled."),
	"template_required": _("Pick an enabled document collection template."),
	"no_template": _("Create a document collection template first."),
	"no_documents": _("The template {template} asks for no enabled document. Edit it, or pick another."),
}

# (http status, message) for the portal. Only the 417 texts say anything specific.
_GUEST = {
	"signature": (401, GENERIC_ERROR),
	"link_invalid": (404, GENERIC_ERROR),
	"closed": (404, GENERIC_ERROR),
	"stale_ref": (404, GENERIC_ERROR),
	"schema": (400, GENERIC_ERROR),
	"unknown_document": (417, "Unknown document."),
	"file_type": (417, "This file type is not accepted."),
	"file_size": (417, "This file is too large."),
	"no_file": (417, "No file was received."),
}


class _Blank(dict):
	def __missing__(self, key):
		return key


def hr_text(code: str, translate=None, **ctx) -> str:
	"""The message HR sees for `code`. `translate` (frappe._ at the edge) is applied to the
	template before the context fills it."""
	template = _HR_TEXT.get(code, _("Something went wrong."))
	if translate:
		template = translate(template)
	return template.format_map(_Blank(ctx))


def guest_answer(code: str) -> tuple[int, str]:
	"""Anything not listed (including HR-only codes) is the generic 404."""
	return _GUEST.get(code, (404, GENERIC_ERROR))

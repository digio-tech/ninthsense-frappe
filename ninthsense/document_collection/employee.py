"""Create > Employee, extended (R3), and the Employee hooks (R7, R19)."""

import re

import frappe
from frappe import _
from frappe.utils import get_link_to_form

from ninthsense.core.config import HR_ROLES
from ninthsense.core.masking import UNREADABLE, mask_aadhaar
from ninthsense.document_collection import service
from ninthsense.document_collection.log import log_failure

_MASKED = re.compile(r"^XXXX XXXX \d{4}$")


@frappe.whitelist()
def make_employee(source_name: str, target_doc: str | dict | None = None):
	"""HRMS's make_employee, then the fill. Same signature, same unsaved Employee.

	Registered in override_whitelisted_methods, so the native button lands here. Anyone HRMS lets
	create the Employee still can; only HR users get the fill.
	"""
	from hrms.hr.doctype.employee_onboarding.employee_onboarding import make_employee as native

	doc = native(source_name, target_doc)
	if not set(HR_ROLES) & set(frappe.get_roles()):
		return doc

	# The fill writes its report on the request. A failure takes all of it back, its messages too.
	savepoint = "nso_fill_employee"
	frappe.db.savepoint(savepoint)
	messages = len(getattr(frappe.local, "message_log", None) or [])
	try:
		_notify(service.fill_employee(doc, source_name))
	except Exception as exc:
		# The fill is an extra: it must never stop HR creating the Employee (FR-018). The fill may
		# have half-changed `doc`, so HRMS's own values are rebuilt.
		frappe.db.rollback(save_point=savepoint)
		if getattr(frappe.local, "message_log", None):
			del frappe.local.message_log[messages:]
		log_failure(
			"Document collection: fill on Create Employee", "fill_failed", exc=exc, onboarding=source_name
		)
		frappe.msgprint(
			_("Couldn't fill from the candidate's documents; the form has HRMS's values only."),
			indicator="orange",
			alert=True,
		)
		doc = native(source_name, target_doc)
	return doc


def _notify(result: dict | None):
	if not result:
		return
	if result["state"] == "no_data":
		frappe.msgprint(
			_("The candidate's documents have not arrived. Saving this Employee closes their link."),
			indicator="orange",
			alert=True,
		)
		return
	if result["state"] == "no_mapping":
		frappe.msgprint(
			_(
				"Nothing was filled: {0} has no field mapping to read. Check its document collection template."
			).format(get_link_to_form(service.REQUEST, result["request"])),
			indicator="orange",
			alert=True,
		)
		return
	message = _("Filled {0} fields from the candidate's documents, {1} skipped. Fill report: {2}.").format(
		result["filled"], result["skipped"], get_link_to_form(service.REQUEST, result["request"])
	)
	verdict = result.get("verification_result")
	if verdict and verdict != "Passed":
		message += " " + _("9thSense's result: {0}.").format(_(verdict))
	mismatch = result.get("name_mismatch")
	if mismatch:
		message += " " + _(
			"The documents name {0}, not {1}: the name fields were left as they are. Check the person."
		).format(
			frappe.bold(frappe.utils.escape_html(mismatch[0])),
			frappe.bold(frappe.utils.escape_html(mismatch[1])),
		)
	frappe.msgprint(message, indicator="green", alert=True)
	if result.get("newer_link_open"):
		frappe.msgprint(
			_(
				"The candidate was sent a newer link that has not been used. These values are from "
				"their earlier documents, and saving this Employee closes the newer link."
			),
			indicator="orange",
			alert=True,
		)


def validate(doc, method=None):
	"""The Aadhaar field only ever holds the last four digits, whatever wrote it (R7)."""
	value = doc.get("aadhaar_number")
	if value and value != UNREADABLE and not _MASKED.match(str(value)):
		doc.aadhaar_number = mask_aadhaar(value)


def after_insert(doc, method=None):
	if doc.get("job_applicant"):
		service.complete_for_employee(doc)

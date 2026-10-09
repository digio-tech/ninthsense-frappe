"""HR actions on Employee Onboarding (contracts/hr-actions.md). Every function is @hr_action."""

import frappe
from frappe import _

from ninthsense.core.field_catalogue import ENTRIES, SECTIONS, get_entry
from ninthsense.core.mapping_rules import allowed_sources
from ninthsense.document_collection import service
from ninthsense.document_collection.decorators import hr_action, hr_read


@frappe.whitelist(methods=["POST"])
@hr_action
def send_onboarding_link(
	employee_onboarding: str, template: str | None = None, config: dict | None = None
) -> dict:
	frappe.get_doc("Employee Onboarding", employee_onboarding).check_permission("read")
	return service.send_link(employee_onboarding, config, template=template or None)


@frappe.whitelist()
@hr_action
def get_send_options(employee_onboarding: str, config: dict | None = None) -> dict:
	"""The enabled templates for the Send picker, and the request's current one (FR-040)."""
	frappe.get_doc("Employee Onboarding", employee_onboarding).check_permission("read")
	name = service.find_request(employee_onboarding)
	return {
		"templates": [
			{"name": row.name, "is_default": row.is_default} for row in service.enabled_templates()
		],
		"current_template": frappe.db.get_value(service.REQUEST, name, "template") if name else None,
	}


@frappe.whitelist()
@hr_read
def get_onboarding_request(employee_onboarding: str) -> dict | None:
	"""The request's state, for the button label. Nothing personal.

	Only the role is checked, not the Settings: the button must still read Completed or Cancelled
	while the Settings are incomplete. Sending checks them.
	"""
	frappe.get_doc("Employee Onboarding", employee_onboarding).check_permission("read")
	name = service.find_request(employee_onboarding)
	if not name:
		return None
	return frappe.db.get_value(
		service.REQUEST,
		name,
		["name", "status", "link_emailed", "link_expires_on"],
		as_dict=True,
	)


@frappe.whitelist()
@hr_read
def get_mapping_options() -> dict:
	"""Every field a template can map, with the document types that may supply each (FR-043).

	The role only: an HR Manager sets up templates before the portal is configured.

	Doc-free: the editor filters these by the open form's documents, so a document added there
	is usable at once. A field this site lacks (a regional one, say) is left out, and so are
	disabled types and every source `allowed_sources` refuses.
	"""
	name_by_code = {
		row.document_code: row.name
		for row in frappe.get_all(
			service.DOCUMENT_TYPE, filters={"is_enabled": 1}, fields=["name", "document_code"]
		)
	}
	fields = []
	for entry in ENTRIES:
		codes = allowed_sources(entry.key, name_by_code)
		if codes and _field_exists(entry.key):
			fields.append(
				{
					"key": entry.key,
					"label": _(entry.label),
					"section": entry.section,
					"documents": [name_by_code[code] for code in codes],
				}
			)
	return {"sections": [{"value": s, "label": _(s)} for s in SECTIONS], "fields": fields}


def _field_exists(key: str) -> bool:
	"""Whether this site has the field a catalogue key lands on, looking inside a child table."""
	entry = get_entry(key)
	meta = frappe.get_meta(entry.target_doctype)
	if entry.target_child_table:
		table = meta.get_field(entry.target_child_table)
		if not table or table.fieldtype != "Table":
			return False
		meta = frappe.get_meta(table.options)
	return bool(meta.get_field(entry.target_field))

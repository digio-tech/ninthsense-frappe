"""What install creates (R15). Each seeder creates only what is absent and never overwrites HR's
edits (H18). No company, department, job, letterhead or demo data.
"""

import os

import frappe
from frappe.modules.import_file import import_file_by_path

from ninthsense.core.mapping_rows import DEFAULT_MAPPING_ROWS

EMAIL_TEMPLATE = "Document Request Link"
TEMPLATE = "Document Collection Template"
DEFAULT_TEMPLATE = "Standard Onboarding"

# Comma-separated extensions, the form a template's document rows accept.
IMG = "pdf,jpeg,jpg,png"
PDF = "pdf"
PIC = "jpeg,jpg,png"

# name, category, file types, max MB, document code -- the old app's DOCUMENT_TYPES.
#
# The code is the key the portal addresses each requested document by, and what it maps the
# classifier's answers onto. A code is a contract: add a new one rather than renaming an
# existing one, and bump core.config.CATALOGUE_VERSION when the set changes.
DOCUMENT_TYPES = (
	("Aadhaar Card Front", "Identity", IMG, 3, "aadhaar_front"),
	("Aadhaar Card Back", "Identity", IMG, 3, "aadhaar_back"),
	("PAN Card", "Identity", IMG, 3, "pan_card"),
	("Driving License", "Identity", IMG, 3, "driving_license"),
	("Passport", "Identity", PDF, 3, "passport"),
	("Passport Photo", "Photo", PIC, 1, "passport_photo"),
	("Graduation Certificate", "Education", IMG, 3, "graduation_certificate"),
	("Masters Certificate", "Education", IMG, 3, "masters_certificate"),
	("Resume", "Employment", PDF, 3, "resume"),
	("Offer Letter", "Employment", PDF, 3, "offer_letter"),
	("Experience Letter", "Employment", PDF, 3, "experience_letter"),
	("Latest Pay Slip", "Employment", PDF, 3, "latest_pay_slip"),
	("Bank Account Statement", "Banking", PDF, 3, "bank_statement"),
	("Cancelled Cheque", "Banking", IMG, 3, "cancelled_cheque"),
)

HELP_TEXT = {
	"Aadhaar Card Front": "The side showing your photo, name and date of birth.",
	"Aadhaar Card Back": "The side showing your address.",
	"Passport Photo": "A recent passport-size photograph on a plain background.",
	"Cancelled Cheque": "Write CANCELLED across the face. Do not sign it.",
	"Bank Account Statement": "Any statement from the last three months showing your name and account number.",
}

# "Standard Onboarding"'s documents (R15, FR-044): exactly the documents its mapping reads.
DEFAULT_TEMPLATE_DOCUMENTS = (
	("Aadhaar Card Front", 1),
	("PAN Card", 1),
	("Resume", 1),
	("Graduation Certificate", 1),
	("Cancelled Cheque", 1),
	("Latest Pay Slip", 0),
	("Bank Account Statement", 0),
	("Passport", 0),
)

INVITE_EMAIL_SUBJECT = "Complete your onboarding for {{ doc.company }}"

# Rendered with the context from core.invite_email.build_invite_context(). Every
# `doc.<key>` below has to exist there -- test_invite_email asserts it, because
# Jinja renders an unknown key as nothing and the gap reaches the candidate.
#
# `job_title` is guarded rather than assumed: an onboarding without a Designation
# is ordinary, and "Your role: ." is worse than no line at all.
INVITE_EMAIL_BODY = """<p>Hello {{ doc.candidate_name }},</p>

<p>Welcome to {{ doc.company }}. Before your first day we need a few documents from you.</p>

{% if doc.job_title -%}
<p>Role: <b>{{ doc.job_title }}</b></p>
{%- endif %}

<p>We have asked for <b>{{ doc.document_count }} document(s)</b>. Uploading them takes a few minutes,
and you only need to do it once.</p>

<p>Open this link to upload your documents:</p>
<p style="word-break:break-all">{{ doc.link }}</p>

<p>The link is unique to you and works for {{ doc.valid_days }} days{% if doc.expires_on %}, until
<b>{{ doc.expires_on }}</b>{% endif %}. Please do not forward it.</p>

<p>If anything is unclear, reply to this email and our HR team will help.</p>
"""


AADHAAR_FIELD = {
	"fieldname": "aadhaar_number",
	"label": "Aadhaar Number (last 4 digits)",
	"fieldtype": "Data",
	"read_only": 1,
}


def after_install():
	create_india_employee_fields()
	create_aadhaar_field()
	seed_document_types()
	seed_email_template()
	seed_default_template()
	ship_desk_navigation()


def create_india_employee_fields():
	"""HRMS's India fields on Employee (PAN, IFSC, MICR, PF account and the rest), FR-034.

	HRMS creates them only when a Company with country India is saved, which on a new site is
	the setup wizard. Installing this app first would leave the mapping targeting fields that do
	not exist. HRMS's own function, so the fields are exactly the ones an Indian company gets;
	`update=True` makes a later run from HRMS a no-op.
	"""
	try:
		from hrms.regional.india.setup import make_custom_fields
	except ImportError:
		return

	make_custom_fields(update=True)
	frappe.clear_cache(doctype="Employee")


def create_aadhaar_field():
	"""Employee.aadhaar_number (R7), after PAN where the India fields exist, else after the
	personal email. Created only if absent."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	meta = frappe.get_meta("Employee")
	if meta.has_field(AADHAAR_FIELD["fieldname"]):
		return
	insert_after = "pan_number" if meta.has_field("pan_number") else "personal_email"
	create_custom_field("Employee", {**AADHAAR_FIELD, "insert_after": insert_after})
	frappe.clear_cache(doctype="Employee")


def seed_document_types():
	for name, category, file_types, size, code in DOCUMENT_TYPES:
		if frappe.db.exists("Employee Document Type", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Employee Document Type",
				"document_type_name": name,
				"document_code": code,
				"category": category,
				"is_enabled": 1,
				"default_allowed_file_types": file_types,
				"default_max_file_size_mb": size,
				"help_text": HELP_TEXT.get(name),
			}
		).insert(ignore_permissions=True)


def seed_email_template():
	if frappe.db.exists("Email Template", EMAIL_TEMPLATE):
		return
	frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": EMAIL_TEMPLATE,
			"subject": INVITE_EMAIL_SUBJECT,
			"use_html": 1,
			"response_html": INVITE_EMAIL_BODY,
		}
	).insert(ignore_permissions=True)


def seed_default_template():
	""" "Standard Onboarding", only when no template exists, so HR's edits survive every migrate
	(FR-044, H18): the documents of R15 with each type's defaults, and DEFAULT_MAPPING_ROWS.
	"""
	if frappe.db.count(TEMPLATE):
		return
	types = {
		row.name: row
		for row in frappe.get_all(
			"Employee Document Type",
			filters={"is_enabled": 1},
			fields=["name", "document_code", "default_allowed_file_types", "default_max_file_size_mb"],
		)
	}
	template = frappe.new_doc(TEMPLATE)
	template.template_name = DEFAULT_TEMPLATE
	template.is_enabled = 1
	template.is_default = 1
	for name, mandatory in DEFAULT_TEMPLATE_DOCUMENTS:
		if name not in types:
			continue
		template.append(
			"documents",
			{
				"document_type": name,
				"is_mandatory": mandatory,
				"allowed_file_types": types[name].default_allowed_file_types,
				"max_file_size_mb": types[name].default_max_file_size_mb,
			},
		)
	if not template.documents:
		return

	# A row whose documents are not in the template is left out, never saved broken.
	name_of = {types[d.document_type].document_code: d.document_type for d in template.documents}
	for key, source, fallback in DEFAULT_MAPPING_ROWS:
		if source not in name_of:
			continue
		template.append(
			"field_mapping",
			{
				"field_key": key,
				"source_document": name_of[source],
				"fallback_document": name_of.get(fallback),
			},
		)
	template.insert(ignore_permissions=True)


# (app-level folder, doctype) of each v16 record, all named after the workspace (R14).
V16_NAVIGATION = (("workspace_sidebar", "Workspace Sidebar"), ("desktop_icon", "Desktop Icon"))
NAVIGATION_NAME = "Document Collection"
NAVIGATION_FILE = "document_collection.json"
# The `app` the shipped v16 records are filed under (R14).
NAVIGATION_APP = "hrms"


def ship_desk_navigation():
	"""Put the app's own Workspace Sidebar and Desktop Icon in place of the ones v16 generates (R14).

	v16 builds both for any workspace that has none, and the generated rows are as new as the
	install, so the shipped files would never replace them in the ordinary sync. Develop reads
	its own Sidebar and Dock; v15 has no Workspace Sidebar. A row the app shipped (`standard`)
	is left alone. Not a patch: patches are marked done on install and there are no earlier
	installs. Also run after every migrate: v16's orphan sweep deletes these rows, since their
	`app` is hrms, whose folder does not hold them.
	"""
	if frappe.db.exists("DocType", "Sidebar"):
		return
	if not frappe.db.exists("DocType", "Workspace Sidebar"):
		return

	for folder, doctype in V16_NAVIGATION:
		if not frappe.db.exists("DocType", doctype):
			continue
		path = frappe.get_app_path("ninthsense", folder, NAVIGATION_FILE)
		if not os.path.exists(path):
			continue
		if frappe.db.get_value(doctype, NAVIGATION_NAME, "standard"):
			continue
		import_file_by_path(path, force=True, ignore_version=True)


def before_uninstall():
	"""Remove the v16 Workspace Sidebar and Desktop Icon the app shipped (R14).

	Uninstall deletes the navigation filed under the app being removed; these are filed under
	hrms, so they would stay behind and point at the deleted workspace.
	"""
	for _folder, doctype in V16_NAVIGATION:
		if not frappe.db.exists("DocType", doctype):
			continue
		row = frappe.db.get_value(doctype, NAVIGATION_NAME, ["app", "standard"], as_dict=True)
		if row and row.app == NAVIGATION_APP and row.standard:
			frappe.delete_doc(doctype, NAVIGATION_NAME, ignore_permissions=True, force=True)

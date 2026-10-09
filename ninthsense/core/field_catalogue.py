"""Every Employee field the fill can write, and where each document holds it.

Frappe-free, so it is testable without a site. A row of a template's field mapping names a
catalogue key, the document to read it from and an optional fallback document -- nothing
else. Everything else is fixed here: the field the value lands on, the child-table row it
belongs to, how it is shaped, and which key of a document's `extracted` block holds it.

A document is named by its `document_code` (Employee Document Type), never by
what 9thSense's classifier calls it: the portal translates classifier labels onto
codes, so nothing here depends on a provider's vocabulary. Adding a field or a
source is an edit to this file.
"""

from dataclasses import dataclass

from ninthsense.core.mapping import NO_PATHS, resolve_value
from ninthsense.core.transforms import apply_transform

#: The catalogue's groups.
SECTIONS = (
	"Personal Information",
	"Address Verification",
	"Employee Information",
	"Banking",
	"Statutory",
)

#: What a transform dropping a value that was found is reported as.
TRANSFORM_DROPPED = "transform_dropped"


@dataclass(frozen=True)
class Entry:
	"""One fillable field.

	`sources` is `((document_code, key), ...)` in the order the old Template form
	offered the documents: `key` is the one key of that document's `extracted` block
	the value is read from. `target_field` defaults to the key.
	"""

	key: str
	label: str
	section: str
	sources: tuple
	target_doctype: str = "Employee"
	target_field: str = ""
	target_child_table: str | None = None
	target_row_key: str | None = None
	transform: str | None = None

	def __post_init__(self):
		if not self.target_field:
			object.__setattr__(self, "target_field", self.key)

	@property
	def codes(self) -> tuple[str, ...]:
		return tuple(code for code, _key in self.sources)

	def paths_for(self, code: str | None) -> tuple[str, ...]:
		key = dict(self.sources).get(code)
		return (key,) if key else ()


def _child(table, row_key, field, label, sources, transform=None) -> Entry:
	"""A field of one Employee child-table row. Entries sharing a row key fill one row."""
	return Entry(
		key=f"{table}.{field}",
		label=label,
		section="Employee Information",
		sources=sources,
		target_field=field,
		target_child_table=table,
		target_row_key=row_key,
		transform=transform,
	)


_PERSONAL = "Personal Information"
_ADDRESS = "Address Verification"
_EMPLOYMENT = "Employee Information"
_BANKING = "Banking"
_STATUTORY = "Statutory"

ENTRIES = (
	# ------------------------------------------------------------ personal
	Entry(
		"first_name",
		"First Name",
		_PERSONAL,
		(
			("aadhaar_front", "name"),
			("pan_card", "name"),
			("passport", "given_name"),
			("resume", "full_name"),
			("offer_letter", "employee_name"),
			("latest_pay_slip", "employee_name"),
		),
		transform="Name Part",
	),
	Entry(
		"middle_name",
		"Middle Name",
		_PERSONAL,
		(("aadhaar_front", "name"), ("pan_card", "name"), ("passport", "given_name")),
		transform="Name Part",
	),
	Entry(
		"last_name",
		"Last Name",
		_PERSONAL,
		(
			("aadhaar_front", "name"),
			("pan_card", "name"),
			("passport", "surname"),
			("resume", "full_name"),
			("offer_letter", "employee_name"),
			("latest_pay_slip", "employee_name"),
		),
		transform="Name Part",
	),
	Entry("gender", "Gender", _PERSONAL, (("aadhaar_front", "gender"),), transform="Gender"),
	Entry(
		"date_of_birth",
		"Date of Birth",
		_PERSONAL,
		(
			("aadhaar_front", "date_of_birth"),
			("pan_card", "date_of_birth"),
			("passport", "date_of_birth"),
			("driving_license", "date_of_birth"),
			("resume", "date_of_birth"),
		),
	),
	Entry("marital_status", "Marital Status", _PERSONAL, (("resume", "marital_status"),)),
	Entry("cell_number", "Mobile", _PERSONAL, (("resume", "phone"), ("bank_statement", "mobile_number"))),
	Entry("personal_email", "Personal Email", _PERSONAL, (("resume", "email"), ("bank_statement", "email"))),
	# ------------------------------------------------------------- address
	Entry(
		"current_address",
		"Current Address",
		_ADDRESS,
		(
			("aadhaar_back", "address"),
			("aadhaar_front", "address"),
			("resume", "current_address"),
			("bank_statement", "address"),
		),
		transform="Compose Address",
	),
	Entry(
		"permanent_address",
		"Permanent Address",
		_ADDRESS,
		(
			("aadhaar_back", "address"),
			("aadhaar_front", "address"),
			("resume", "current_address"),
			("bank_statement", "address"),
		),
		transform="Compose Address",
	),
	# ---------------------------------------------------------- employment
	Entry("date_of_joining", "Date of Joining", _EMPLOYMENT, (("offer_letter", "date_of_joining"),)),
	Entry(
		"designation",
		"Designation",
		_EMPLOYMENT,
		(("offer_letter", "designation"), ("latest_pay_slip", "designation")),
	),
	Entry(
		"department",
		"Department",
		_EMPLOYMENT,
		(("offer_letter", "department"), ("latest_pay_slip", "department")),
	),
	Entry("ctc", "CTC", _EMPLOYMENT, (("offer_letter", "salary"),)),
	# One education row. 9thSense reads graduation and masters certificates alike, so
	# both carry the same keys; a resume's highest qualification is the fallback.
	_child(
		"education",
		"degree",
		"school_univ",
		"Education: Institution",
		(
			("graduation_certificate", "institution"),
			("masters_certificate", "institution"),
			("resume", "highest_qualification_institution"),
		),
	),
	_child(
		"education",
		"degree",
		"qualification",
		"Education: Degree",
		(
			("graduation_certificate", "degree"),
			("masters_certificate", "degree"),
			("resume", "highest_qualification"),
		),
	),
	_child(
		"education",
		"degree",
		"year_of_passing",
		"Education: Year of Passing",
		(
			("graduation_certificate", "year_of_passing"),
			("masters_certificate", "year_of_passing"),
			("resume", "highest_qualification_year"),
		),
		transform="Year",
	),
	_child(
		"education",
		"degree",
		"class_per",
		"Education: Percentage",
		(("graduation_certificate", "percentage"), ("masters_certificate", "percentage")),
	),
	# One previous-employment row. The resume's current employer is, by the time an
	# Employee exists, the previous one; the experience letter and the latest pay slip
	# come from that same employer.
	_child(
		"external_work_history",
		"previous",
		"company_name",
		"Previous Employer",
		(
			("resume", "current_employer"),
			("experience_letter", "employer_name"),
			("latest_pay_slip", "employer_name"),
		),
	),
	_child(
		"external_work_history",
		"previous",
		"designation",
		"Previous Designation",
		(
			("resume", "current_designation"),
			("experience_letter", "designation"),
			("latest_pay_slip", "designation"),
		),
	),
	_child(
		"external_work_history",
		"previous",
		"salary",
		"Previous Salary",
		(("experience_letter", "salary"),),
	),
	_child(
		"external_work_history",
		"previous",
		"total_experience",
		"Total Experience",
		(("resume", "total_experience_years"),),
	),
	# ------------------------------------------------------------- banking
	Entry(
		"bank_name",
		"Bank Name",
		_BANKING,
		(
			("cancelled_cheque", "bank_name"),
			("bank_statement", "bank_name"),
			("latest_pay_slip", "bank_name"),
		),
	),
	Entry(
		"bank_ac_no",
		"Bank Account Number",
		_BANKING,
		(
			("cancelled_cheque", "account_number"),
			("bank_statement", "account_number"),
			("latest_pay_slip", "bank_account"),
		),
	),
	Entry(
		"ifsc_code",
		"IFSC Code",
		_BANKING,
		(("cancelled_cheque", "ifsc_code"), ("bank_statement", "ifsc_code")),
	),
	Entry("micr_code", "MICR Code", _BANKING, (("cancelled_cheque", "micr_code"),)),
	# ----------------------------------------------------------- statutory
	Entry(
		"pan_number",
		"PAN",
		_STATUTORY,
		(
			("pan_card", "pan_number"),
			("latest_pay_slip", "pan_number"),
		),
	),
	Entry(
		"aadhaar_number",
		"Aadhaar Number",
		_STATUTORY,
		(("aadhaar_front", "aadhaar_number"),),
	),
	Entry("provident_fund_account", "PF Account", _STATUTORY, (("latest_pay_slip", "pf_number"),)),
	Entry(
		"passport_number",
		"Passport Number",
		_STATUTORY,
		(("passport", "passport_number"),),
	),
	Entry("date_of_issue", "Passport Issue Date", _STATUTORY, (("passport", "date_of_issue"),)),
	Entry(
		"valid_upto",
		"Passport Valid Until",
		_STATUTORY,
		(("passport", "valid_upto"),),
	),
	Entry(
		"place_of_issue",
		"Passport Place of Issue",
		_STATUTORY,
		(("passport", "place_of_issue"),),
	),
)

CATALOGUE = {entry.key: entry for entry in ENTRIES}


def get_entry(key: str | None) -> Entry | None:
	return CATALOGUE.get((key or "").strip())


@dataclass
class Resolution:
	"""What one mapping row produced.

	`document` is the document the value came from, or the source document when
	nothing did. `claimed` is every `(document, path)` a value was found at, so a
	caller can tell mapped keys from unmapped ones even when a transform dropped
	the value. `reasons` is `[(document, reason)]` for each attempt that failed, in
	order, with a reason from mapping.py or TRANSFORM_DROPPED.
	"""

	value: object = None
	raw: object = None
	path: str | None = None
	document: str | None = None
	role: str | None = None
	claimed: list | None = None
	reasons: list | None = None


def resolve(entry: Entry, attempts) -> Resolution:
	"""Read one field, trying each attempt in turn: the source, then the fallback.

	`attempts` is `[(role, document, code, extracted)]`, where `extracted` is that
	document's `extracted` block or None. The first attempt that yields a value
	after the entry's transform wins.
	"""
	claimed: list = []
	reasons: list = []

	for role, document, code, extracted in attempts:
		paths = entry.paths_for(code)
		raw, path, reason = resolve_value(extracted, paths) if paths else (None, None, NO_PATHS)

		if path:
			claimed.append((document, path))

		if reason:
			reasons.append((document, reason))
			continue

		value = apply_transform(raw, entry.transform, entry.target_field, path)

		if value is None or (isinstance(value, str) and not value.strip()):
			reasons.append((document, TRANSFORM_DROPPED))
			continue

		return Resolution(value, raw, path, document, role, claimed, reasons)

	first = attempts[0][1] if attempts else None
	return Resolution(
		document=first, role=attempts[0][0] if attempts else None, claimed=claimed, reasons=reasons
	)

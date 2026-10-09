"""The mapping install seeds into "Standard Onboarding" (research R5, R24). Frappe-free.

The Employee-targeted rows of the old app's two curated essential sets: a catalogue key, the
primary document code, and the fallback code or None. This is only the seeded template's
mapping; Create Employee reads the request's template mapping, which HR may edit.
"""

DEFAULT_MAPPING_ROWS: tuple[tuple[str, str, str | None], ...] = (
	("first_name", "aadhaar_front", "pan_card"),
	("middle_name", "aadhaar_front", "pan_card"),
	("last_name", "aadhaar_front", "pan_card"),
	("gender", "aadhaar_front", None),
	("aadhaar_number", "aadhaar_front", None),
	("date_of_birth", "aadhaar_front", "pan_card"),
	("pan_number", "pan_card", None),
	("current_address", "resume", None),
	("permanent_address", "resume", None),
	("cell_number", "resume", None),
	("personal_email", "resume", None),
	("provident_fund_account", "latest_pay_slip", None),
	("education.school_univ", "graduation_certificate", None),
	("education.qualification", "graduation_certificate", None),
	("education.year_of_passing", "graduation_certificate", None),
	("education.class_per", "graduation_certificate", None),
	("external_work_history.company_name", "resume", None),
	("external_work_history.designation", "resume", None),
	("external_work_history.total_experience", "resume", None),
	("bank_name", "cancelled_cheque", "bank_statement"),
	("bank_ac_no", "cancelled_cheque", "bank_statement"),
	("ifsc_code", "cancelled_cheque", "bank_statement"),
	("micr_code", "cancelled_cheque", None),
	("passport_number", "passport", None),
	("date_of_issue", "passport", None),
	("valid_upto", "passport", None),
	("place_of_issue", "passport", None),
)

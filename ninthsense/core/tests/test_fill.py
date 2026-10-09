"""plan_fill and candidates_from (research R4). Frappe-free; resolve_link is a fake."""

import copy
import json
import unittest
from pathlib import Path

from ninthsense.core.extraction import document_step, extraction_rows
from ninthsense.core.fill import (
	ALREADY_FILLED,
	FILLED,
	INVALID,
	FieldSpec,
	candidates_from,
	plan_fill,
)
from ninthsense.core.mapping_rows import DEFAULT_MAPPING_ROWS
from ninthsense.core.masking import mask_payload

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "completion-mock.json"

EDUCATION = FieldSpec(
	"education",
	"Education",
	"Table",
	"Employee Education",
	child_fields=(
		FieldSpec("school_univ", "School/University", "Small Text"),
		FieldSpec("qualification", "Qualification", "Data"),
		FieldSpec("year_of_passing", "Year of Passing", "Int"),
		FieldSpec("class_per", "Class / Percentage", "Data"),
	),
)
WORK = FieldSpec(
	"external_work_history",
	"External Work History",
	"Table",
	"Employee External Work History",
	child_fields=(
		FieldSpec("company_name", "Company", "Data"),
		FieldSpec("designation", "Designation", "Data"),
		FieldSpec("total_experience", "Total Experience", "Data"),
	),
)
FIELDS = (
	FieldSpec("first_name", "First Name", "Data"),
	FieldSpec("middle_name", "Middle Name", "Data"),
	FieldSpec("last_name", "Last Name", "Data"),
	FieldSpec("gender", "Gender", "Link", "Gender"),
	FieldSpec("aadhaar_number", "Aadhaar Number (last 4 digits)", "Data"),
	FieldSpec("date_of_birth", "Date of Birth", "Date"),
	FieldSpec("pan_number", "PAN Number", "Data", length=10),
	FieldSpec("current_address", "Current Address", "Small Text"),
	FieldSpec("permanent_address", "Permanent Address", "Small Text"),
	FieldSpec("cell_number", "Mobile", "Data", "Phone"),
	FieldSpec("personal_email", "Personal Email", "Data", "Email"),
	FieldSpec("provident_fund_account", "Provident Fund Account", "Data"),
	FieldSpec("bank_name", "Bank Name", "Data"),
	FieldSpec("bank_ac_no", "Bank A/C No.", "Data"),
	FieldSpec("ifsc_code", "IFSC Code", "Data"),
	FieldSpec("micr_code", "MICR Code", "Data"),
	FieldSpec("passport_number", "Passport Number", "Data"),
	FieldSpec("date_of_issue", "Date of Issue", "Date"),
	FieldSpec("valid_upto", "Valid Up To", "Date"),
	FieldSpec("place_of_issue", "Place of Issue", "Data"),
	EDUCATION,
	WORK,
)


class FakeLinks:
	"""Stands in for the frappe layer's resolve_link: known names only, never creates."""

	def __init__(self, records=None):
		self.records = records or {"Gender": ["Male", "Female"], "Department": ["Engineering"]}
		self.calls = []

	def __call__(self, doctype, value, company):
		self.calls.append((doctype, value, company))
		return next((n for n in self.records.get(doctype, ()) if n.casefold() == value.casefold()), None)


def plan(candidates, current=None, fields=FIELDS, links=None):
	return plan_fill(fields, current or {}, candidates, links or FakeLinks(), "Test Co")


def rows(result, fieldname):
	return [r for r in result.report if r.fieldname == fieldname]


class Scalars(unittest.TestCase):
	def test_an_empty_data_field_is_filled(self):
		result = plan({"pan_number": "ABCPV1234F"}, {"pan_number": "  "})
		self.assertEqual(result.values, {"pan_number": "ABCPV1234F"})
		(row,) = result.report
		self.assertEqual((row.outcome, row.field_label, row.value), (FILLED, "PAN Number", "ABCPV1234F"))

	def test_a_different_value_is_reported_with_both(self):
		result = plan({"bank_name": "HDFC Bank"}, {"bank_name": "ICICI Bank"})
		self.assertEqual(result.values, {})
		(row,) = result.report
		self.assertEqual(
			(row.outcome, row.value, row.existing_value), (ALREADY_FILLED, "HDFC Bank", "ICICI Bank")
		)

	def test_the_same_value_after_trim_and_casefold_is_not_reported(self):
		result = plan({"bank_name": " hdfc bank "}, {"bank_name": "HDFC Bank"})
		self.assertEqual((result.values, result.report), ({}, []))

	def test_a_check_field_is_never_filled_or_reported(self):
		fields = (FieldSpec("pan_number", "PAN Number", "Check"),)
		result = plan({"pan_number": "1"}, {"pan_number": 0}, fields=fields)
		self.assertEqual((result.values, result.report), ({}, []))

	def test_a_data_value_over_its_length_is_invalid(self):
		result = plan({"pan_number": "ABCPV1234FXYZ"})
		(row,) = result.report
		self.assertEqual(row.outcome, INVALID)
		self.assertIn("too long", row.reason)
		self.assertEqual(result.values, {})

	def test_a_data_value_without_a_length_holds_140(self):
		self.assertEqual(plan({"bank_name": "x" * 140}).values, {"bank_name": "x" * 140})
		self.assertIn("too long", plan({"bank_name": "x" * 141}).report[0].reason)

	def test_small_text_is_never_truncated(self):
		address = "12 Sample Street, " * 20
		self.assertEqual(plan({"current_address": address}).values, {"current_address": address.strip()})

	def test_email_is_validated(self):
		self.assertEqual(
			plan({"personal_email": "a.b@example.com"}).values, {"personal_email": "a.b@example.com"}
		)
		(row,) = plan({"personal_email": "not-an-email"}).report
		self.assertEqual((row.outcome, row.reason), (INVALID, "not a valid email address"))

	def test_phone_is_validated(self):
		self.assertEqual(plan({"cell_number": "+91 90000 00001"}).values, {"cell_number": "+91 90000 00001"})
		(row,) = plan({"cell_number": "call me maybe"}).report
		self.assertEqual((row.outcome, row.reason), (INVALID, "not a valid phone number"))

	def test_date_accepts_iso_and_rejects_impossible_or_malformed(self):
		self.assertEqual(plan({"date_of_birth": "1996-04-18"}).values, {"date_of_birth": "1996-04-18"})
		self.assertEqual(plan({"date_of_birth": "18/04/1996"}).values, {"date_of_birth": "1996-04-18"})
		for bad in ("31-02-2000", "20X5", "2000-02-31"):
			(row,) = plan({"date_of_birth": bad}).report
			self.assertEqual(row.outcome, INVALID, bad)
			self.assertEqual(row.value, bad)

	def test_int_accepts_a_whole_number_string_and_rejects_others(self):
		# Employee's one Int target is a child field.
		spec_fields = (
			FieldSpec(
				"education",
				"Education",
				"Table",
				child_fields=(FieldSpec("year_of_passing", "Year of Passing", "Int"),),
			),
		)
		ok = plan({"education.year_of_passing": "2015"}, fields=spec_fields)
		self.assertEqual(ok.child_rows, {"education": [{"year_of_passing": 2015}]})
		bad = plan({"education.year_of_passing": "20X5"}, fields=spec_fields)
		self.assertEqual(bad.child_rows, {})
		(row,) = bad.report
		self.assertEqual((row.outcome, row.reason), (INVALID, "not a whole number"))

	def test_currency_strips_symbols_grouping_and_spaces(self):
		fields = (
			FieldSpec(
				"external_work_history",
				"External Work History",
				"Table",
				child_fields=(FieldSpec("salary", "Salary", "Currency"),),
			),
		)
		# salary is a catalogue key that DEFAULT_MAPPING_ROWS does not read; plan_fill takes any key.
		result = plan({"external_work_history.salary": "₹ 1,20,000"}, fields=fields)
		self.assertEqual(result.child_rows, {"external_work_history": [{"salary": 120000.0}]})
		(row,) = plan({"external_work_history.salary": "lots"}, fields=fields).report
		self.assertEqual(row.outcome, INVALID)

	def test_select_is_case_insensitive_and_stored_as_the_option(self):
		fields = (FieldSpec("marital_status", "Marital Status", "Select", "\nSingle\nMarried"),)
		self.assertEqual(
			plan({"marital_status": "SINGLE"}, fields=fields).values, {"marital_status": "Single"}
		)
		(row,) = plan({"marital_status": "Complicated"}, fields=fields).report
		self.assertEqual((row.outcome, row.reason), (INVALID, "not one of the options"))

	def test_a_link_takes_the_resolved_name(self):
		links = FakeLinks()
		result = plan({"gender": "female"}, links=links)
		self.assertEqual(result.values, {"gender": "Female"})
		self.assertEqual(links.calls, [("Gender", "female", "Test Co")])

	def test_an_unknown_link_value_is_invalid_and_nothing_is_created(self):
		links = FakeLinks()
		result = plan({"gender": "M"}, links=links)
		self.assertEqual(result.values, {})
		(row,) = result.report
		self.assertEqual((row.outcome, row.reason), (INVALID, "no Gender named 'M'"))
		self.assertEqual(links.records["Gender"], ["Male", "Female"])

	def test_a_placeholder_gives_no_row(self):
		for value in ("N/A", "not available", "-", "  "):
			result = plan({"pan_number": value, "education.qualification": value})
			self.assertEqual((result.values, result.child_rows, result.report), ({}, {}, []), value)

	def test_a_field_the_site_lacks_is_ignored(self):
		result = plan({"aadhaar_number": "XXXX XXXX 7777"}, fields=(FIELDS[0],))
		self.assertEqual((result.values, result.report), ({}, []))


class Names(unittest.TestCase):
	def test_empty_parts_are_filled_from_one_full_name(self):
		candidates = candidates_from([("aadhaar_front", "name", "ASHA RANI VERMA")], DEFAULT_MAPPING_ROWS)
		result = plan(candidates)
		self.assertEqual(result.values, {"first_name": "Asha", "middle_name": "Rani", "last_name": "Verma"})

	def test_a_prefilled_first_name_is_reported_and_the_others_filled(self):
		candidates = candidates_from([("aadhaar_front", "name", "Asha Rani Verma")], DEFAULT_MAPPING_ROWS)
		result = plan(candidates, {"first_name": "Ash"})
		self.assertEqual(result.values, {"middle_name": "Rani", "last_name": "Verma"})
		(row,) = rows(result, "first_name")
		self.assertEqual((row.outcome, row.value, row.existing_value), (ALREADY_FILLED, "Asha", "Ash"))

	def test_a_different_person_fills_no_part_and_reports_employee_name(self):
		candidates = candidates_from([("aadhaar_front", "name", "Ravi Kumar Shah")], DEFAULT_MAPPING_ROWS)
		result = plan(dict(candidates, pan_number="ABCPV1234F"), {"employee_name": "Asha Verma"})
		self.assertEqual(result.values, {"pan_number": "ABCPV1234F"})
		self.assertEqual(result.name_mismatch, ("Ravi Kumar Shah", "Asha Verma"))
		(row,) = rows(result, "employee_name")
		self.assertEqual(
			(row.outcome, row.field_label, row.value, row.existing_value),
			(ALREADY_FILLED, "Employee Name", "Ravi Kumar Shah", "Asha Verma"),
		)
		for part in ("first_name", "middle_name", "last_name"):
			self.assertEqual(rows(result, part), [])

	def test_a_middle_name_only_on_the_document_is_a_mismatch(self):
		candidates = candidates_from([("aadhaar_front", "name", "Asha Rani Verma")], DEFAULT_MAPPING_ROWS)
		result = plan(candidates, {"employee_name": "Asha Verma"})
		self.assertEqual(result.values, {})
		self.assertEqual(result.name_mismatch, ("Asha Rani Verma", "Asha Verma"))

	def test_the_same_name_up_to_case_and_spacing_fills_the_parts(self):
		candidates = candidates_from([("aadhaar_front", "name", "ASHA RANI VERMA")], DEFAULT_MAPPING_ROWS)
		result = plan(candidates, {"employee_name": "  asha  rani verma "})
		self.assertIsNone(result.name_mismatch)
		self.assertEqual(result.values, {"first_name": "Asha", "middle_name": "Rani", "last_name": "Verma"})
		self.assertEqual(rows(result, "employee_name"), [])

	def test_no_native_name_fills_the_parts(self):
		candidates = candidates_from([("aadhaar_front", "name", "Asha Verma")], DEFAULT_MAPPING_ROWS)
		result = plan(candidates, {"employee_name": ""})
		self.assertIsNone(result.name_mismatch)
		self.assertEqual(result.values, {"first_name": "Asha", "last_name": "Verma"})


EDUCATION_CANDIDATES = {
	"education.school_univ": "Sample Institute",
	"education.qualification": "B.E.",
	"education.year_of_passing": 2018,
	"education.class_per": "82.5",
}


class Tables(unittest.TestCase):
	def test_an_empty_table_gets_one_row_from_its_entries(self):
		result = plan(EDUCATION_CANDIDATES, {"education": 0})
		self.assertEqual(
			result.child_rows,
			{
				"education": [
					{
						"school_univ": "Sample Institute",
						"qualification": "B.E.",
						"year_of_passing": 2018,
						"class_per": "82.5",
					}
				]
			},
		)
		self.assertEqual([r.outcome for r in result.report], [FILLED] * 4)
		self.assertEqual(result.report[0].field_label, "Education: School/University")
		self.assertEqual(result.report[0].fieldname, "education.school_univ")

	def test_a_table_with_rows_is_reported_once(self):
		result = plan(EDUCATION_CANDIDATES, {"education": [{"qualification": "B.Sc."}]})
		self.assertEqual(result.child_rows, {})
		(row,) = result.report
		self.assertEqual(
			(row.outcome, row.fieldname, row.existing_value), (ALREADY_FILLED, "education", "1 row(s)")
		)

	def test_a_row_with_only_invalid_fields_is_dropped_and_its_fields_reported(self):
		fields = (
			FieldSpec(
				"education",
				"Education",
				"Table",
				child_fields=(
					FieldSpec("year_of_passing", "Year of Passing", "Int"),
					FieldSpec("qualification", "Qualification", "Data", length=3),
				),
			),
		)
		result = plan(
			{"education.year_of_passing": "20X5", "education.qualification": "B.E. Computer Science"},
			fields=fields,
		)
		self.assertEqual(result.child_rows, {})
		self.assertEqual([r.outcome for r in result.report], [INVALID, INVALID])
		self.assertEqual(
			[r.fieldname for r in result.report], ["education.year_of_passing", "education.qualification"]
		)

	def test_a_row_keeps_its_valid_fields_and_reports_the_invalid_one(self):
		candidates = dict(EDUCATION_CANDIDATES, **{"education.year_of_passing": "20X5"})
		result = plan(candidates)
		self.assertEqual(len(result.child_rows["education"]), 1)
		self.assertNotIn("year_of_passing", result.child_rows["education"][0])
		self.assertEqual(rows(result, "education.year_of_passing")[0].outcome, INVALID)


class Purity(unittest.TestCase):
	def test_inputs_are_not_mutated(self):
		fields = copy.deepcopy(FIELDS)
		current = {"first_name": "Ash", "education": [{"qualification": "B.Sc."}]}
		candidates = {"first_name": "Asha", "last_name": "Verma", "education.qualification": "B.E."}
		snapshot = (copy.deepcopy(current), copy.deepcopy(candidates))
		plan_fill(fields, current, candidates, FakeLinks(), "Test Co")
		self.assertEqual((current, candidates), snapshot)
		self.assertEqual(fields, FIELDS)


class CandidatesFrom(unittest.TestCase):
	def fixture_rows(self):
		payload = mask_payload(json.loads(FIXTURE.read_text()))
		return extraction_rows(document_step(payload))

	def test_reads_the_fixture_through_the_mapping(self):
		candidates = candidates_from(self.fixture_rows(), DEFAULT_MAPPING_ROWS)
		self.assertEqual(candidates["first_name"], "Asha")
		self.assertEqual(candidates["middle_name"], "Rani")
		self.assertEqual(candidates["last_name"], "Verma")
		self.assertEqual(candidates["gender"], "Female")
		self.assertEqual(candidates["aadhaar_number"], "XXXX XXXX 7777")
		self.assertEqual(candidates["pan_number"], "ABCPV1234F")
		self.assertEqual(candidates["education.year_of_passing"], 2018)
		self.assertEqual(candidates["ifsc_code"], "HDFC0000001")
		self.assertEqual(candidates["external_work_history.company_name"], "Digio India")
		self.assertNotIn("999988887777", json.dumps(candidates))

	def test_keys_follow_mapping_order_and_skip_unread_documents(self):
		candidates = candidates_from(self.fixture_rows(), DEFAULT_MAPPING_ROWS)
		keys = list(candidates)
		self.assertEqual(keys[:3], ["first_name", "middle_name", "last_name"])
		self.assertNotIn("designation", candidates)

	def test_the_fallback_is_read_when_the_primary_has_nothing(self):
		candidates = candidates_from(
			[("bank_statement", "ifsc_code", "SBIN0000001"), ("cancelled_cheque", "ifsc_code", "N/A")],
			DEFAULT_MAPPING_ROWS,
		)
		self.assertEqual(candidates, {"ifsc_code": "SBIN0000001"})

	def test_a_year_that_cannot_be_read_is_offered_as_read(self):
		candidates = candidates_from(
			[("graduation_certificate", "year_of_passing", "20X5")], DEFAULT_MAPPING_ROWS
		)
		self.assertEqual(candidates, {"education.year_of_passing": "20X5"})
		(row,) = plan(candidates).report
		self.assertEqual((row.outcome, row.reason), (INVALID, "not a whole number"))

	def test_the_rows_passed_decide_the_source(self):
		rows = (("first_name", "passport", None), ("pan_number", "latest_pay_slip", "pan_card"))
		candidates = candidates_from(self.fixture_rows(), rows)
		self.assertEqual(candidates, {"first_name": "Asha", "pan_number": "ABCPV1234F"})
		self.assertEqual(candidates_from(self.fixture_rows(), ()), {})

	def test_a_passport_fills_the_names_without_splitting_the_surname(self):
		rows = tuple((key, "passport", None) for key in ("first_name", "middle_name", "last_name"))
		candidates = candidates_from(
			[("passport", "given_name", "ASHA KUMARI"), ("passport", "surname", "SEN VERMA")], rows
		)
		self.assertEqual(
			candidates, {"first_name": "Asha", "middle_name": "Kumari", "last_name": "Sen Verma"}
		)
		one_word = candidates_from(
			[("passport", "given_name", "Asha"), ("passport", "surname", "Verma")], rows
		)
		self.assertEqual(one_word, {"first_name": "Asha", "last_name": "Verma"})

	def test_a_padded_row_key_is_keyed_as_the_catalogue_spells_it(self):
		candidates = candidates_from(
			[("aadhaar_front", "name", "Asha Verma")], ((" first_name ", "aadhaar_front", None),)
		)
		self.assertEqual(candidates, {"first_name": "Asha"})

	def test_a_missing_middle_name_is_not_offered(self):
		candidates = candidates_from([("aadhaar_front", "name", "Asha Verma")], DEFAULT_MAPPING_ROWS)
		self.assertEqual(candidates, {"first_name": "Asha", "last_name": "Verma"})

	def test_dotted_keys_are_read_as_blocks(self):
		# A nested `extracted` block arrives flattened; the catalogue digs into it again.
		candidates = candidates_from(
			[("resume", "current_address.line1", "12 MG Road"), ("resume", "current_address.city", "Pune")],
			DEFAULT_MAPPING_ROWS,
		)
		self.assertEqual(candidates["current_address"], "12 MG Road, Pune")


if __name__ == "__main__":
	unittest.main()


SALARY_MODE = FieldSpec("salary_mode", "Salary Mode", "Select", "\nBank\nCash\nCheque")


class SalaryMode(unittest.TestCase):
	"""HRMS shows the bank fields only when Salary Mode is Bank, so filled bank details set it."""

	def test_filled_bank_details_set_an_empty_salary_mode_to_bank(self):
		result = plan({"bank_ac_no": "50100123456789"}, {"salary_mode": None}, fields=(*FIELDS, SALARY_MODE))
		self.assertEqual(result.values["salary_mode"], "Bank")
		(row,) = rows(result, "salary_mode")
		self.assertEqual((row.outcome, row.field_label, row.value), (FILLED, "Salary Mode", "Bank"))

	def test_a_salary_mode_hr_already_chose_is_left_alone(self):
		result = plan(
			{"bank_ac_no": "50100123456789"}, {"salary_mode": "Cash"}, fields=(*FIELDS, SALARY_MODE)
		)
		self.assertNotIn("salary_mode", result.values)
		self.assertEqual(rows(result, "salary_mode"), [])

	def test_no_bank_detail_filled_leaves_salary_mode_alone(self):
		result = plan(
			{"bank_ac_no": "50100123456789"},
			{"bank_ac_no": "111", "salary_mode": None},
			fields=(*FIELDS, SALARY_MODE),
		)
		self.assertNotIn("salary_mode", result.values)

	def test_a_site_without_salary_mode_is_unaffected(self):
		result = plan({"bank_ac_no": "50100123456789"})
		self.assertEqual(result.values, {"bank_ac_no": "50100123456789"})

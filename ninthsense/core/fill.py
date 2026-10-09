"""The fill: what Create Employee writes onto the unsaved Employee (research R4). Frappe-free.

`candidates_from` turns the request's extraction rows into one value per catalogue key, read
from the documents the template's mapping rows name. `plan_fill` decides, field by field, what to set, what
to add to empty child tables, and what to report. It never mutates its inputs, and its only
collaborator is the injected `resolve_link`, which never creates a record.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from ninthsense.core.field_catalogue import TRANSFORM_DROPPED, get_entry, resolve
from ninthsense.core.mapping import clean_value, dig

# Employee Fill Result's outcomes, spelled as its Select options.
FILLED = "Filled"
ALREADY_FILLED = "Skipped – already filled"  # noqa: RUF001 -- the Select option has an en dash
INVALID = "Skipped – invalid"  # noqa: RUF001
ATTACH_FAILED = "Attach failed"

#: What a Data column holds when its docfield sets no length.
DATA_LENGTH = 140

#: The name parts, in order, and the native full name they would rebuild on save (ERPNext's
#: Employee.set_employee_name).
NAME_KEYS = ("first_name", "middle_name", "last_name")
EMPLOYEE_NAME = "employee_name"
EMPLOYEE_NAME_LABEL = "Employee Name"

#: HRMS shows these Employee fields only while Salary Mode is Bank, so filling any of them
#: sets an empty Salary Mode to Bank; otherwise the filled values are on the form but hidden.
BANK_FIELDS = frozenset({"bank_name", "bank_ac_no", "ifsc_code", "micr_code"})
SALARY_MODE = "salary_mode"
SALARY_MODE_BANK = "Bank"

TEXT_TYPES = frozenset({"Small Text", "Text", "Long Text"})
NUMBER_TYPES = frozenset({"Currency", "Float", "Percent"})
TABLE_TYPES = frozenset({"Table"})

#: Transforms whose dropping of a value that was found means the value is malformed, not
#: absent. Such a value is offered as read, so the report says why it was not used.
_REPORT_DROPPED = frozenset({"Year"})

# Frappe's own patterns (frappe.utils PHONE_NUMBER_PATTERN and EMAIL_MATCH_PATTERN).
_PHONE = re.compile(r"[0-9\ \+\_\-\,\.\*\#\(\)]{1,20}")
_EMAIL = re.compile(
	r"[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
	r"@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?",
	re.IGNORECASE,
)
_ISO_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
# Indian documents print the day first.
_DAY_FIRST_DATE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})")
_WHOLE_NUMBER = re.compile(r"[+-]?\d+")
_CURRENCY_NOISE = re.compile(r"[₹,\s]|^(?:rs\.?|inr)", re.IGNORECASE)


@dataclass(frozen=True)
class FieldSpec:
	"""One Employee field, from its docfield. `child_fields` holds a table's own fields."""

	fieldname: str
	label: str
	fieldtype: str
	options: str | None = None
	length: int | None = None
	child_fields: tuple = ()


@dataclass(frozen=True)
class ReportRow:
	outcome: str
	field_label: str
	fieldname: str
	value: str | None = None
	existing_value: str | None = None
	reason: str | None = None


@dataclass
class FillPlan:
	values: dict = field(default_factory=dict)
	child_rows: dict = field(default_factory=dict)
	report: list = field(default_factory=list)
	#: `(documents' name, native name)` when the documents name someone else; else None.
	name_mismatch: tuple | None = None


# ------------------------------------------------------------------ candidates


def _put(tree: dict, dotted_key: str, value):
	"""Store a flattened `a.b` key back as a nested block, so catalogue paths dig into it."""
	parts = dotted_key.split(".")
	node = tree
	for part in parts[:-1]:
		child = node.setdefault(part, {})
		if not isinstance(child, dict):
			return
		node = child
	node.setdefault(parts[-1], value)


def candidates_from(extractions, rows) -> dict:
	"""`{catalogue key: value}` in mapping order, from `(document_code, key, value)` rows.

	`rows` is the mapping, as `(field_key, source_code, fallback_code_or_None)`. Each key is read
	from its source document, then its fallback, with the catalogue's transform applied. A key
	with nothing to offer is left out.
	"""
	documents: dict = {}
	for code, key, value in extractions or ():
		if code and key:
			_put(documents.setdefault(code, {}), key, value)

	candidates = {}
	for key, primary, fallback in rows or ():
		entry = get_entry(key)
		if entry is None:
			continue
		attempts = [("Source", primary, primary, documents.get(primary))]
		if fallback:
			attempts.append(("Fallback", fallback, fallback, documents.get(fallback)))
		result = resolve(entry, attempts)
		# Keyed by the catalogue's own spelling, so a padded row key cannot hide a name part
		# from the name-mismatch guard.
		if result.value is not None:
			candidates[entry.key] = result.value
		elif entry.transform in _REPORT_DROPPED and result.claimed:
			dropped = [doc for doc, reason in result.reasons or () if reason == TRANSFORM_DROPPED]
			code, path = next((c, p) for c, p in result.claimed if c in dropped)
			candidates[entry.key] = dig(documents[code], path)
	return candidates


# ---------------------------------------------------------------------- values


def _is_empty(value) -> bool:
	return value is None or (isinstance(value, str) and not value.strip())


def _is_placeholder(value) -> bool:
	return _is_empty(clean_value(value))


def _text(value) -> str | None:
	if value is None:
		return None
	if isinstance(value, datetime | date):
		return value.isoformat()
	if isinstance(value, float) and value.is_integer():
		return str(int(value))
	return str(value).strip()


def _same(a, b) -> bool:
	"""Equal after trimming and case-folding (numbers by value)."""
	numbers = (int, float)
	if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool):
		return float(a) == float(b)
	return (_text(a) or "").casefold() == (_text(b) or "").casefold()


def _date(raw):
	if isinstance(raw, datetime):
		raw = raw.date()
	if isinstance(raw, date):
		return True, raw.isoformat(), None
	text = _text(raw) or ""
	iso = _ISO_DATE.fullmatch(text)
	day_first = None if iso else _DAY_FIRST_DATE.fullmatch(text)
	if iso:
		year, month, day = (int(p) for p in iso.groups())
	elif day_first:
		day, month, year = (int(p) for p in day_first.groups())
	else:
		return False, None, "not a date (YYYY-MM-DD)"
	try:
		return True, date(year, month, day).isoformat(), None
	except ValueError:
		return False, None, "not a real date"


def _coerce(spec: FieldSpec, raw, resolve_link, company):
	"""`(ok, value, reason)`: the value as the field stores it, or why it cannot hold it."""
	fieldtype = spec.fieldtype
	text = _text(raw) or ""

	if fieldtype == "Data":
		kind = (spec.options or "").strip()
		if kind == "Email" and not _EMAIL.fullmatch(text):
			return False, None, "not a valid email address"
		if kind == "Phone" and not (_PHONE.fullmatch(text) and any(c.isdigit() for c in text)):
			return False, None, "not a valid phone number"
		limit = spec.length or DATA_LENGTH
		if len(text) > limit:
			return False, None, f"too long ({len(text)} characters, at most {limit})"
		return True, text, None

	if fieldtype in TEXT_TYPES:
		return True, text, None

	if fieldtype == "Date":
		return _date(raw)

	if fieldtype == "Int":
		if isinstance(raw, int) and not isinstance(raw, bool):
			return True, raw, None
		if _WHOLE_NUMBER.fullmatch(text):
			return True, int(text), None
		return False, None, "not a whole number"

	if fieldtype in NUMBER_TYPES:
		if isinstance(raw, int | float) and not isinstance(raw, bool):
			return True, float(raw), None
		try:
			return True, float(_CURRENCY_NOISE.sub("", text)), None
		except ValueError:
			return False, None, "not a number"

	if fieldtype == "Select":
		options = [o for o in (spec.options or "").split("\n") if o.strip()]
		match = next((o for o in options if o.strip().casefold() == text.casefold()), None)
		if match is None:
			return False, None, "not one of the options"
		return True, match, None

	if fieldtype == "Link":
		name = resolve_link(spec.options, text, company)
		if not name:
			return False, None, f"no {spec.options} named '{text}'"
		return True, name, None

	return False, None, f"a {fieldtype} field is not filled"


def _plan_field(spec, label, fieldname, existing, raw, resolve_link, company):
	"""`(fill, value, report_row)` for one field. A row of None means nothing to report."""
	if _is_placeholder(raw):
		return False, None, None

	if not _is_empty(existing):
		shown = raw
		if spec.fieldtype != "Link":
			ok, value, _reason = _coerce(spec, raw, resolve_link, company)
			shown = value if ok else raw
		if _same(shown, existing):
			return False, None, None
		return False, None, ReportRow(ALREADY_FILLED, label, fieldname, _text(shown), _text(existing))

	ok, value, reason = _coerce(spec, raw, resolve_link, company)
	if not ok:
		return False, None, ReportRow(INVALID, label, fieldname, _text(raw), reason=reason)
	return True, value, ReportRow(FILLED, label, fieldname, _text(value))


def _row_count(value) -> int:
	if isinstance(value, list | tuple):
		return len(value)
	return int(value or 0)


def _plan_table(spec: FieldSpec, items, existing_rows, resolve_link, company, plan: FillPlan):
	"""Rows for an empty table, one per row key. A table that has rows is reported once."""
	offered = [(entry, raw) for entry, raw in items if not _is_placeholder(raw)]
	if not offered:
		return

	if _row_count(existing_rows):
		plan.report.append(
			ReportRow(
				ALREADY_FILLED,
				spec.label,
				spec.fieldname,
				", ".join(_text(raw) for _entry, raw in offered),
				f"{_row_count(existing_rows)} row(s)",
			)
		)
		return

	children = {child.fieldname: child for child in spec.child_fields}
	by_row: dict = {}
	for entry, raw in offered:
		by_row.setdefault(entry.target_row_key, []).append((entry, raw))

	for row_items in by_row.values():
		row, filled, invalid = {}, [], []
		for entry, raw in row_items:
			child = children.get(entry.target_field)
			if child is None or child.fieldtype == "Check":
				continue
			fill, value, report = _plan_field(
				child,
				f"{spec.label}: {child.label}",
				f"{spec.fieldname}.{child.fieldname}",
				None,
				raw,
				resolve_link,
				company,
			)
			if fill:
				row[child.fieldname] = value
				filled.append(report)
			elif report:
				invalid.append(report)
		if row:
			plan.child_rows.setdefault(spec.fieldname, []).append(row)
			plan.report.extend(filled)
		plan.report.extend(invalid)


def _normal_name(value) -> str:
	return " ".join((_text(value) or "").split()).casefold()


def _name_mismatch(current: dict, candidates: dict) -> tuple | None:
	"""`(documents' name, native name)` when the parts would rebuild a different Employee Name.

	The parts are joined as ERPNext joins them on save. No native name, or no parts, is no
	mismatch.
	"""
	native = _text(current.get(EMPLOYEE_NAME))
	parts = [_text(candidates.get(key)) for key in NAME_KEYS if not _is_placeholder(candidates.get(key))]
	if not native or not parts:
		return None
	documents = " ".join(parts)
	if _normal_name(documents) == _normal_name(native):
		return None
	return documents, native


def plan_fill(fields, current: dict, candidates: dict, resolve_link, company=None) -> FillPlan:
	"""What to set on the Employee, which child rows to add, and the report (R4).

	`fields` are the Employee's FieldSpecs. `current` holds the mapped document's values, and a
	row count (or the rows) per table, plus the native `employee_name`. `candidates` is
	`candidates_from`'s answer. `resolve_link(doctype, value, company)` returns an existing
	record's name or None.

	When the documents' full name differs from the native Employee Name, no name part is filled
	(saving would rename the Employee) and one Employee Name row reports both names.
	"""
	specs = {spec.fieldname: spec for spec in fields}
	plan = FillPlan()
	plan.name_mismatch = _name_mismatch(current, candidates)
	name_reported = False

	# Child-table keys are grouped under their table, at the place of the table's first key.
	order: list = []
	tables: dict = {}
	for key, raw in candidates.items():
		entry = get_entry(key)
		if entry is None:
			continue
		table = entry.target_child_table
		if table:
			if table not in tables:
				tables[table] = []
				order.append(("table", table))
			tables[table].append((entry, raw))
		else:
			order.append(("field", (entry, raw)))

	for kind, item in order:
		if kind == "table":
			spec = specs.get(item)
			if spec is not None and spec.fieldtype in TABLE_TYPES:
				_plan_table(spec, tables[item], current.get(item), resolve_link, company, plan)
			continue
		entry, raw = item
		if plan.name_mismatch and entry.key in NAME_KEYS:
			if not name_reported:
				name_reported = True
				plan.report.append(
					ReportRow(ALREADY_FILLED, EMPLOYEE_NAME_LABEL, EMPLOYEE_NAME, *plan.name_mismatch)
				)
			continue
		spec = specs.get(entry.target_field)
		if spec is None or spec.fieldtype == "Check":
			continue
		fill, value, report = _plan_field(
			spec, spec.label, spec.fieldname, current.get(spec.fieldname), raw, resolve_link, company
		)
		if fill:
			plan.values[spec.fieldname] = value
		if report:
			plan.report.append(report)

	_show_bank_details(specs, current, plan)
	return plan


def _show_bank_details(specs: dict, current: dict, plan: FillPlan):
	"""Set an empty Salary Mode to Bank when bank details were filled, so HRMS shows them."""
	spec = specs.get(SALARY_MODE)
	if spec is None or not BANK_FIELDS & plan.values.keys() or not _is_empty(current.get(SALARY_MODE)):
		return
	if SALARY_MODE_BANK not in (spec.options or "").split("\n"):
		return
	plan.values[SALARY_MODE] = SALARY_MODE_BANK
	plan.report.append(ReportRow(FILLED, spec.label, SALARY_MODE, SALARY_MODE_BANK))

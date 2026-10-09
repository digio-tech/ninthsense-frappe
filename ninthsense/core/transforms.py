"""Named shaping applied to a raw extracted value before it is proposed.

Frappe-free. The transform is chosen on the mapping row rather than inferred from
the fieldname: inference only ever worked because the target was always Employee.
"""

import re

from ninthsense.core.mapping import clean_value

# Gender comes back as a code; Employee.gender links to Gender records by name.
GENDER_CODES = {
	"m": "Male",
	"male": "Male",
	"f": "Female",
	"female": "Female",
	"o": "Other",
	"other": "Other",
	"t": "Transgender",
	"transgender": "Transgender",
}

_YEAR = re.compile(r"\b(19|20)\d{2}\b")

#: Keys that already hold one part of a name. A given name holds the first name and any middle
#: names; a surname is the last name, whole. Every other key holds a full name, which is split.
GIVEN_NAME_KEYS = frozenset({"given_name"})
SURNAME_KEYS = frozenset({"surname"})


def looks_like_address(value) -> bool:
	"""An Aadhaar back side sometimes hands its address back as the name."""
	return isinstance(value, str) and (sum(c.isdigit() for c in value) >= 3 or value.count(",") >= 2)


def name_part(raw, field: str, key: str | None = None):
	"""One part of a person's name from whatever the provider sent.

	9thSense sends a single string. A dict with first/middle/last keys is honoured
	too. All-caps names (PAN prints them that way) are title-cased. `key` is the document key
	the value was read from: a surname is never split, and a given name gives only the first
	and middle names.
	"""
	if isinstance(raw, dict):
		return clean_value(raw.get(field) or raw.get(field.replace("_name", "")))

	raw = clean_value(raw)

	if not isinstance(raw, str) or not raw.strip() or looks_like_address(raw):
		return None

	parts = [p for p in raw.split() if p]

	if not parts:
		return None

	if raw.isupper():
		parts = [p.title() for p in parts]

	key = (key or "").rsplit(".", 1)[-1]
	if key in SURNAME_KEYS:
		return " ".join(parts) if field == "last_name" else None
	if key in GIVEN_NAME_KEYS:
		if field == "first_name":
			return parts[0]
		return (" ".join(parts[1:]) or None) if field == "middle_name" else None

	if field == "first_name":
		return parts[0]

	if field == "last_name":
		return parts[-1] if len(parts) > 1 else None

	return " ".join(parts[1:-1]) or None


def compose_address(block) -> str | None:
	"""A single address line from either a string or a block of parts.

	This is also where PIN lands -- there is no separate pincode field and none is
	created.
	"""
	block = clean_value(block)

	if isinstance(block, str):
		return block.strip() or None

	if not isinstance(block, dict):
		return None

	if clean_value(block.get("full")):
		return str(block["full"]).strip() or None

	parts = [
		clean_value(block.get("line1")),
		clean_value(block.get("line2")),
		clean_value(block.get("city")),
		clean_value(block.get("state")),
		clean_value(block.get("pincode") or block.get("pin") or block.get("zip")),
	]

	joined = ", ".join(str(p).strip() for p in parts if p and str(p).strip())

	return joined or None


def gender(raw) -> str | None:
	"""A Gender record's name from 9thSense's code: "M" -> "Male"."""
	raw = clean_value(raw)
	if not isinstance(raw, str) or not raw.strip():
		return None
	return GENDER_CODES.get(raw.strip().lower(), raw.strip().title())


def year(raw) -> int | None:
	"""The year out of a date-ish value: "May 2017" -> 2017, for an Int field."""
	raw = clean_value(raw)
	if isinstance(raw, int) and 1900 <= raw <= 2099:
		return raw
	match = _YEAR.search(str(raw or ""))
	return int(match.group(0)) if match else None


TRANSFORMS = {
	"Name Part": lambda value, field, key: name_part(value, field, key),
	"Compose Address": lambda value, field, key: compose_address(value),
	"Gender": lambda value, field, key: gender(value),
	"Year": lambda value, field, key: year(value),
	"Title Case": lambda value, field, key: str(value).title(),
}


def apply_transform(value, transform: str | None, target_field: str, source_key: str | None = None):
	"""The value after its named transform. An unknown or blank name is a no-op.

	`source_key` is the document key the value was read from (Name Part needs it).
	"""
	if value is None:
		return None

	handler = TRANSFORMS.get((transform or "").strip())

	if not handler:
		return value

	return handler(value, target_field, source_key)

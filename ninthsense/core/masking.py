"""Aadhaar number masking: only the last four digits are ever stored.

Frappe-free. `portal_api.store_verification` runs the portal's completion payload
through `mask_payload` before anything is saved, so the stored bundle, the
extraction rows, the review panels and the Employee prefill all only ever see
`XXXX XXXX 1234`. The same rule as the Odoo app's `core/masking.py`.
"""

import re

#: Eight masked digits then the last four, however grouped: ours, or 9thSense's own
#: `XXXXXXXX1234`.
_ALREADY_MASKED = re.compile(r"^[Xx*]{8}(\d{4})$")
UNREADABLE = "unreadable"

_SEPARATORS = re.compile(r"[\s-]")

#: Twelve digits, optionally grouped with single spaces or hyphens, not part of a
#: longer number. What an Aadhaar number looks like inside free text.
_AADHAAR_RUN = re.compile(r"(?<!\d)\d(?:[ -]?\d){11}(?!\d)")

#: The blocks of values read off the documents: each document's `extracted`, and
#: the step's and result's `extractions`. Inside them a field is masked by its name
#: rather than by its shape, so a 12-digit bank account number survives.
STRUCTURED = ("extracted", "extractions")


def mask_aadhaar(value) -> str:
	"""`"XXXX XXXX dddd"` for a 12-digit value, however it is grouped.

	Anything else -- a shorter or longer number, letters, a nested value -- cannot be
	trusted to be an Aadhaar number, so it is replaced outright rather than partly
	shown. A value already masked, in any grouping, keeps its last four.
	"""
	if isinstance(value, int) and not isinstance(value, bool):
		value = str(value)
	if not isinstance(value, str):
		return UNREADABLE
	digits = _SEPARATORS.sub("", value)
	already = _ALREADY_MASKED.match(digits)
	if already:
		return f"XXXX XXXX {already.group(1)}"
	if len(digits) == 12 and digits.isdigit():
		return f"XXXX XXXX {digits[-4:]}"
	return UNREADABLE


def is_aadhaar_key(key) -> bool:
	"""A field that holds an Aadhaar number: `aadhaar_number`, `aadhaarNo`, `uid`.

	Not every key mentioning Aadhaar: 9thSense sends `extractions.aadhaar` as the
	whole card, and masking everything under it would wipe the name and date of birth.
	"""
	lowered = re.sub(r"[^a-z]", "", str(key).lower())
	if lowered in ("uid", "uidnumber", "uidno"):
		return True
	return ("aadhaar" in lowered or "aadhar" in lowered) and lowered.endswith(("number", "no", "num"))


def mask_text(text: str) -> str:
	"""Free text with every Aadhaar-shaped run of digits masked."""
	return _AADHAAR_RUN.sub(lambda match: mask_aadhaar(match.group(0)), text)


def _names_aadhaar(value) -> bool:
	"""A document code or block key for an Aadhaar card: `aadhaar_front`, `aadhaar`, `aadharBack`."""
	return isinstance(value, str) and re.sub(r"[^a-z]", "", value.lower()).startswith(("aadhaar", "aadhar"))


def _is_aadhaar_document(value: dict) -> bool:
	return _names_aadhaar(value.get("document_code")) or _names_aadhaar(value.get("detected_document_type"))


def mask_payload(value, *, extracted: bool = False, force: bool = False, by_shape: bool = False):
	"""A copy of `value` with every Aadhaar number masked, at any depth.

	Under a key that names an Aadhaar number every leaf is masked. Inside an `extracted` or
	`extractions` block that is the only masking, so a 12-digit bank account number survives;
	everywhere else -- summaries, check results, notes the provider writes -- free text is
	scrubbed of Aadhaar-shaped runs too, because the provider can put one anywhere in it.

	Two exceptions keep the scrub by shape inside those blocks: a block that is not an object
	(the schema allows a string or a list), and everything read off an Aadhaar card, which holds
	no bank number but may key its number in a way `is_aadhaar_key` does not know.
	"""
	if isinstance(value, dict):
		by_shape = by_shape or _is_aadhaar_document(value)
		masked = {}
		for key, item in value.items():
			child_by_shape = by_shape or (extracted and _names_aadhaar(key) and not is_aadhaar_key(key))
			structured = (extracted or (key in STRUCTURED and isinstance(item, dict))) and not child_by_shape
			masked[key] = mask_payload(
				item,
				extracted=structured,
				force=force or is_aadhaar_key(key),
				by_shape=child_by_shape,
			)
		return masked
	if isinstance(value, list):
		return [mask_payload(item, extracted=extracted, force=force, by_shape=by_shape) for item in value]
	if force:
		return mask_aadhaar(value) if value not in (None, "") else value
	if isinstance(value, str) and not extracted:
		return mask_text(value)
	return value

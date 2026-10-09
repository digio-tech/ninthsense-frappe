"""Reading one mapped value out of what 9thSense returned.

Deliberately free of frappe imports so it is testable without a site. The
candidate paths for each field and document live in field_catalogue.py, whose
`resolve` is the one caller in the extraction paths.
"""

#: Placeholders the provider sends in place of a value.
#: Adding a member silently turns a legitimate value ("Nil" in a bank field) into an
#: absent one, so only add with evidence that 9thSense actually sends it.
NULLISH = frozenset({"", "null", "none", "n/a", "na", "not visible", "not available", "-"})

NO_PATHS = "no_paths"
NO_EXTRACTION = "no_extraction"
NOT_PRESENT = "not_present"


def clean_value(value):
	"""None for the provider's placeholders, the value otherwise."""
	if isinstance(value, str) and value.strip().lower() in NULLISH:
		return None
	return value


def dig(data: dict, path: str):
	"""Follow a dotted path, returning None if any hop is missing."""
	current = data

	for part in path.split("."):
		if not isinstance(current, dict) or part not in current:
			return None
		current = current[part]

	return current


def first_value(data: dict, paths) -> tuple[object, str | None]:
	"""The first candidate path that holds a real value, and which path it was."""
	for path in paths or ():
		value = clean_value(dig(data, path))
		if value is not None and not (isinstance(value, str) and not value.strip()):
			return value, path
	return None, None


def resolve_value(extracted, paths):
	"""`(value, path, reason)` for one mapping row. reason is None on success.

	The reason is for the extraction row's note, so HR can see why a field is
	empty without opening the payload.
	"""
	paths = tuple(paths or ())

	if not paths:
		return None, None, NO_PATHS

	if extracted is None:
		return None, None, NO_EXTRACTION

	value, path = first_value(extracted, paths)

	if value is None:
		return None, None, NOT_PRESENT

	return value, path, None

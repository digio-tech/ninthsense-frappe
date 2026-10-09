"""The values 9thSense read, as flat rows (data-model "Document Extraction"). Frappe-free."""

import json

# The provider's case status, as HR reads it. No verdict of our own (FR-017).
VERIFICATION_RESULTS = {"completed": "Passed", "review": "Needs Review", "failed": "Failed"}
DEFAULT_RESULT = "Needs Review"


def document_step(payload: dict) -> dict:
	"""The document-collection step of a completion, or the first step."""
	steps = payload.get("steps") or []
	step = next((s for s in steps if isinstance(s, dict) and s.get("type") == "document_collection"), None)
	if step is None and steps and isinstance(steps[0], dict):
		step = steps[0]
	return step or {}


def verification_result(payload: dict) -> str:
	return VERIFICATION_RESULTS.get(str(payload.get("status") or "").lower(), DEFAULT_RESULT)


def _text(value) -> str:
	if isinstance(value, bool):
		return "true" if value else "false"
	if isinstance(value, str | int | float):
		return str(value)
	return json.dumps(value, sort_keys=True, default=str)


def _flatten(prefix: str, value, out: list):
	if isinstance(value, dict):
		for key, item in value.items():
			key = str(key)
			if key.startswith("_"):
				continue
			_flatten(f"{prefix}.{key}" if prefix else key, item, out)
		return
	if value is None or value == "":
		return
	if isinstance(value, list):
		parts = [_text(item) for item in value if item is not None and item != ""]
		if parts:
			out.append((prefix, ", ".join(parts)))
		return
	out.append((prefix, _text(value)))


def extraction_rows(step: dict) -> list[tuple[str, str, str]]:
	"""`(document_code, key, value)` for every value in every document's `extracted` block.

	Nested blocks become dotted keys, lists one comma-joined value. Placeholders such as
	"Not visible" are kept as received; the fill treats them as empty.
	"""
	rows = []
	for document in step.get("documents") or []:
		if not isinstance(document, dict):
			continue
		code = document.get("document_code")
		extracted = document.get("extracted")
		if not code or not isinstance(extracted, dict):
			continue
		pairs: list = []
		_flatten("", extracted, pairs)
		rows.extend((code, key, value) for key, value in pairs)
	return rows

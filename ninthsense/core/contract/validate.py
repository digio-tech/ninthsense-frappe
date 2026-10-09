"""The vendored portal contract, checked at entry (R11). Frappe-free.

A failure names the JSON pointer of the first error and never the value there: the value can
be a candidate's extracted identity field.
"""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from ninthsense.core.config import SUPPORTED_SCHEMA_VERSIONS
from ninthsense.core.reasons import OnboardingError

_DIR = Path(__file__).resolve().parent
SCHEMA_FILES = ("request.schema.json", "completion.schema.json")


def _validator(filename: str) -> Draft202012Validator:
	schema = json.loads((_DIR / filename).read_text())
	Draft202012Validator.check_schema(schema)
	return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


_REQUEST = _validator("request.schema.json")
_COMPLETION = _validator("completion.schema.json")


def _pointer(parts) -> str:
	return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _first_error_pointer(validator: Draft202012Validator, obj) -> str | None:
	error = best_match(validator.iter_errors(obj))
	if error is None:
		return None
	parts = list(error.absolute_path)
	if error.validator == "required" and isinstance(error.instance, dict):
		# The missing property's name comes from the schema, not from the body.
		missing = [k for k in error.validator_value if k not in error.instance]
		if missing:
			parts.append(missing[0])
	return _pointer(parts) or "/"


def _validate(validator: Draft202012Validator, obj):
	pointer = _first_error_pointer(validator, obj)
	if pointer is not None:
		raise OnboardingError("schema", context={"pointer": pointer})
	check_version(obj)


def check_version(obj):
	if obj.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
		raise OnboardingError("schema", context={"pointer": "/schema_version"})


def validate_request(obj):
	"""The descriptor this app builds, before it is returned."""
	_validate(_REQUEST, obj)


def validate_completion(obj):
	"""The portal's delivery, before it is masked or stored."""
	_validate(_COMPLETION, obj)


def schema_digests() -> dict[str, str]:
	return {name: hashlib.sha256((_DIR / name).read_bytes()).hexdigest() for name in SCHEMA_FILES}

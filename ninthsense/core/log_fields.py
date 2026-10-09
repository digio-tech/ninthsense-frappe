"""The allow-list for structured log fields. Nothing else reaches a log.

Free-text log calls cannot stop a name, an email or a file body from landing in a log.
Every field goes through `clean_fields` first. Deliberately free of frappe imports.
"""

ALLOWED = frozenset(
	{
		"request",
		"onboarding",
		"employee",
		"portal_request_id",
		"status",
		"outcome",
		"category",
		"duration_ms",
		"count",
		"op",
		"pointer",
		"exception",
	}
)

_SCALAR_TYPES = (str, int, float, bool)


def exception_site(exc: BaseException, root: str = "") -> str:
	"""`Type at path:line` for the innermost frame. Never the message or the locals: either can
	quote the candidate's data."""
	tb = exc.__traceback__
	while tb is not None and tb.tb_next is not None:
		tb = tb.tb_next
	name = type(exc).__name__
	if tb is None:
		return name
	path = tb.tb_frame.f_code.co_filename
	if root and path.startswith(root):
		path = path[len(root) :].lstrip("/")
	return f"{name} at {path}:{tb.tb_lineno}"


def clean_fields(fields: dict) -> dict:
	return {k: v for k, v in fields.items() if k in ALLOWED and isinstance(v, _SCALAR_TYPES)}

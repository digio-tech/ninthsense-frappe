"""Upload checks by content (R12). Frappe-free: the caller asks `filetype` for the extension."""

from ninthsense.core.config import MAX_FILE_SIZE_MB

MB = 1048576

# The same format under two spellings.
_SAME = {"jpg": "jpeg", "jpeg": "jpeg"}


def _canonical(ext: str) -> str:
	ext = ext.strip().lower().lstrip(".")
	return _SAME.get(ext, ext)


def allowed_extensions(allowed: str | None) -> set[str]:
	return {_canonical(p) for p in (allowed or "").split(",") if p.strip()}


def check_upload(content: bytes, detected_extension: str | None, allowed: str, max_mb: int) -> str | None:
	"""The refusal code for an upload, or None when it is acceptable."""
	if not content:
		return "no_file"
	if len(content) > (int(max_mb or 0) or MAX_FILE_SIZE_MB) * MB:
		return "file_size"
	if not detected_extension or _canonical(detected_extension) not in allowed_extensions(allowed):
		return "file_type"
	return None

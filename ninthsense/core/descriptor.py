"""The request-schema 2.0 descriptor the portal renders (contracts/portal-endpoints.md). Frappe-free.

Ported from the old app's `get_request`, `_branding`, `_accept` and `_requested_documents`. The
Frappe layer gathers the inputs; this builds the object and the caller validates it.
"""

import re

from ninthsense.core.config import (
	ALLOWED_EXTENSIONS,
	CALLBACK_PATH,
	CATALOGUE_VERSION,
	GOAL_KEY,
	MAX_FILE_SIZE_MB,
	SCHEMA_VERSION,
	STAGE_LABEL,
)
from ninthsense.core.link_state import OPEN

HEX_COLOUR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
HTTP_URL = re.compile(r"^https?://\S+$")

FEATURES = {"allow_replace_before_submit": True, "on_classifier_disagreement": "warn"}


def branding(org_name: str | None, logo_url: str | None, accent_color: str | None, support_email: str | None):
	"""Only the values the schema accepts. A bad one is left out rather than refusing the link."""
	out = {}
	# Sent whole. The portal truncates for display.
	name = (org_name or "").strip()[:1024]
	if name:
		out["org_name"] = name
	if logo_url and HTTP_URL.match(logo_url):
		out["logo_url"] = logo_url
	if accent_color and HEX_COLOUR.match(accent_color):
		out["accent_color"] = accent_color
	support = (support_email or "").strip()
	if support and EMAIL.match(support):
		out["support_email"] = support
	return out


def accept(allowed_file_types: str | None) -> list[str]:
	"""`pdf, JPG` -> `[".pdf", ".jpg"]`."""
	out = []
	for part in (allowed_file_types or "").split(","):
		ext = part.strip().lower()
		if not ext:
			continue
		if not ext.startswith("."):
			ext = "." + ext
		if ext not in out:
			out.append(ext)
	return out or list(ALLOWED_EXTENSIONS)


def requested_document(row: dict) -> dict:
	"""One Requested Document row (its fieldnames) as a requestedDocument."""
	out = {
		"document_code": row.get("document_code"),
		"label": (row.get("document_type") or row.get("document_code") or "")[:120],
		"order": int(row.get("idx") or 0),
		"mandatory": bool(row.get("is_mandatory")),
		"accept": accept(row.get("allowed_file_types")),
		# max_file_size_mb stays a megabyte figure for HR; the bytes are derived here.
		"max_bytes": (int(row.get("max_file_size_mb") or 0) or MAX_FILE_SIZE_MB) * 1048576,
	}
	group = (row.get("display_group") or "").strip()
	if group:
		out["group"] = group[:60]
	help_text = (row.get("help_text") or "").strip()
	if help_text:
		out["help"] = help_text[:400]
	# Which 9thSense document fills this slot, so the portal can recover where a bulk upload
	# was filed without asking 9thSense again.
	if row.get("staged_verification_document_id"):
		out["verification_document_id"] = row["staged_verification_document_id"]
	return out


def build_descriptor(inputs: dict) -> dict:
	"""`inputs`: ref, instance, state, expires_at, org_name, logo_url, accent_color,
	support_email, display_name, application, documents (row dicts), replaced_ids.

	A link that is not open gets the same skeleton with nothing to collect; the portal shows
	its own submitted, expired or revoked screen from `state`.
	"""
	state = inputs["state"]
	step = {"id": "docs", "type": "document_collection", "documents": []}
	descriptor = {
		"schema_version": SCHEMA_VERSION,
		"ref": inputs["ref"],
		"hrms": {"system": "frappe-hrms", "instance": inputs["instance"]},
		"goal_key": GOAL_KEY,
		"stage": STAGE_LABEL,
		"catalogue_version": CATALOGUE_VERSION,
		"state": state,
		"branding": branding(
			inputs.get("org_name"),
			inputs.get("logo_url"),
			inputs.get("accent_color"),
			inputs.get("support_email"),
		),
		"steps": [step],
		"completion": {"callback_path": CALLBACK_PATH},
	}
	if inputs.get("expires_at"):
		descriptor["expires_at"] = inputs["expires_at"]

	if state != OPEN:
		return descriptor

	display_name = (inputs.get("display_name") or "").strip()[:120]
	if display_name:
		descriptor["subject"] = {"display_name": display_name}
	descriptor["features"] = dict(FEATURES)
	step["documents"] = [requested_document(row) for row in inputs.get("documents") or []]
	replaced = [i for i in inputs.get("replaced_ids") or [] if isinstance(i, str) and i]
	if replaced:
		step["replaced_verification_document_ids"] = replaced
	descriptor["x-hrms"] = {"application": inputs["application"]}
	return descriptor

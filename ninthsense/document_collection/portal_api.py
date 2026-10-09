"""Guest endpoints for the candidate portal (contracts/portal-endpoints.md).

The portal calls these at the old app's addresses; hooks.py routes them here (R1). The link
code is the candidate's only identity and the first argument of every call. Every function is
@portal_guest, which turns each failure into the portal's answer. Frappe never talks to
9thSense: it receives files and results from the portal.
"""

import json
import time
from zoneinfo import ZoneInfo

import frappe
from frappe.utils import get_datetime, get_system_timezone, get_url

from ninthsense.core.callback_signature import SIGNATURE_HEADER, verify_callback_signature
from ninthsense.core.contract.validate import validate_request
from ninthsense.core.descriptor import build_descriptor
from ninthsense.core.reasons import OnboardingError
from ninthsense.document_collection import service
from ninthsense.document_collection.decorators import portal_guest


@frappe.whitelist(allow_guest=True, methods=["GET"])
@portal_guest
def get_request(token: str) -> dict:
	"""The page config for a known link: branding, plus the documents to collect while it is open.

	A submitted, expired or revoked link answers 200 with the same skeleton and no documents, so
	the portal can show its branded Thank-you or invalid page. Unknown codes stay a 404.
	"""
	request = service.resolve_link(token)
	descriptor = build_descriptor(_descriptor_inputs(request))
	try:
		validate_request(descriptor)
	except OnboardingError as exc:
		# Our own drift, caught before the portal sees it. Logged, and answered like any
		# other failure.
		raise OnboardingError(
			"link_invalid", context={"category": "descriptor_schema", "pointer": exc.context.get("pointer")}
		)
	return descriptor


@frappe.whitelist(allow_guest=True, methods=["POST"])
@portal_guest
def store_document(token: str, document_code: str, verification_document_id: str | None = None) -> dict:
	"""One uploaded file, pushed by the portal after 9thSense accepted it. Multipart."""
	request = service.resolve_link(token, for_update=True)
	uploaded = (frappe.request.files or {}).get("file") if frappe.request else None
	content = uploaded.stream.read() if uploaded else b""
	file_url = service.stage_upload(request, document_code, verification_document_id, content)
	return {"ok": True, "file_url": file_url}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@portal_guest
def discard_document(token: str, verification_document_id: str) -> dict:
	"""The candidate no longer wants an upload. 9thSense keeps it; Frappe stops offering it."""
	request = service.resolve_link(token, for_update=True)
	service.discard_upload(request, verification_document_id)
	return {"ok": True}


@frappe.whitelist(allow_guest=True, methods=["POST"])
@portal_guest
def store_verification(token: str, payload: dict | str | None = None) -> dict:
	"""The completion bundle. The signature is checked before the code or the body is read.

	The code alone proves nothing: it travels in the candidate's own address bar.
	"""
	_require_signature()
	request = service.resolve_link(token, for_update=True)
	service.accept_delivery(request, _read_payload(payload))
	return {"ok": True}


def _descriptor_inputs(request) -> dict:
	company = (
		frappe.db.get_value(
			"Company", request.company, ["company_name", "company_logo", "email"], as_dict=True
		)
		or frappe._dict()
	)
	settings = frappe.get_single("Document Collection Settings")
	return {
		"ref": request.link_ref,
		"instance": get_url(),
		"state": service.current_link_state(request),
		"expires_at": _iso(request.link_expires_on),
		"org_name": company.company_name or request.company,
		"logo_url": get_url(company.company_logo) if company.company_logo else None,
		"accent_color": settings.portal_accent_color,
		"support_email": (settings.support_email or "").strip() or company.email,
		"display_name": ((request.candidate_name or "").split() or [""])[0],
		"application": request.name,
		# A row kept only for its earlier delivery is not asked for (I-1, R9).
		"documents": [row.as_dict() for row in service.requested_rows(request)],
		"replaced_ids": service.replaced_ids(request),
	}


def _iso(value) -> str | None:
	if not value:
		return None
	dt = get_datetime(value)
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=ZoneInfo(get_system_timezone()))
	return dt.isoformat()


def _require_signature():
	"""The raw body is what was signed. Re-serialising the parsed arguments would change the
	bytes (spacing, key order) and every signature would fail."""
	raw = frappe.request.data if frappe.request else b""
	if isinstance(raw, str):
		raw = raw.encode()
	header = frappe.get_request_header(SIGNATURE_HEADER) if frappe.request else None
	secret = frappe.get_single("Document Collection Settings").get_password(
		"callback_secret", raise_exception=False
	)
	category = verify_callback_signature(raw, header, [secret], int(time.time()))
	if category:
		raise OnboardingError("signature", context={"category": category})


def _read_payload(payload):
	"""The portal posts JSON {token, payload}. Frappe maps it onto the arguments; a string or
	the raw body is tolerated. Anything that is not an object is left for the schema check."""
	try:
		if payload is None and frappe.request and frappe.request.data:
			body = json.loads(frappe.request.data)
			payload = body.get("payload") if isinstance(body, dict) else None
		if isinstance(payload, str):
			payload = json.loads(payload)
	except ValueError:
		return None
	return payload

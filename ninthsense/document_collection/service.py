"""Services: every write to a Document Collection Request goes through here (plan, VII).

Endpoints (hr_api, portal_api, hooks) call these. Every status write sets `flags.via_service`,
which the request's controller requires for a status change.
"""

import functools
import json
from dataclasses import asdict

import filetype
import frappe
from frappe import _
from frappe.core.doctype.file.exceptions import MaxFileSizeReachedError
from frappe.utils import add_days, get_datetime, get_link_to_form, now_datetime

from ninthsense.core.config import LINK_VALIDITY_DAYS, MAX_TOKEN_LENGTH
from ninthsense.core.contract.validate import validate_completion
from ninthsense.core.extraction import document_step, extraction_rows, verification_result
from ninthsense.core.field_catalogue import get_entry
from ninthsense.core.file_types import check_upload
from ninthsense.core.fill import (
	ALREADY_FILLED,
	ATTACH_FAILED,
	BANK_FIELDS,
	EMPLOYEE_NAME,
	FILLED,
	INVALID,
	SALARY_MODE,
	FieldSpec,
	candidates_from,
	plan_fill,
)
from ninthsense.core.link_codes import codes_match, hash_code, mint_link
from ninthsense.core.link_state import OPEN, SUBMITTED, link_state
from ninthsense.core.masking import mask_payload
from ninthsense.core.reasons import OnboardingError
from ninthsense.document_collection import email
from ninthsense.document_collection.decorators import REQUEST_FLAG
from ninthsense.document_collection.log import log_event, log_failure
from ninthsense.document_collection.wiring import EMAIL

REQUEST = "Document Collection Request"
TEMPLATE = "Document Collection Template"
DOCUMENT_TYPE = "Employee Document Type"
CLOSED_STATUSES = ("Completed", "Cancelled")
# What a second insert on the unique `employee_onboarding` raises (see _insert_request).
_LOST_RACE = (frappe.DuplicateEntryError, frappe.UniqueValidationError)
# Statuses that accept a delivery (R10).
RECEIVING_STATUSES = ("Link Sent", "Data Received")
STAGED_FIELDS = (
	"staged_file",
	"staged_file_name",
	"staged_file_size_bytes",
	"staged_verification_document_id",
	"staged_on",
)
DELIVERED_FIELDS = ("file", "file_name", "file_size_bytes", "verification_document_id")
RESULT_FIELDS = (
	"detected_document_type",
	"is_detected_type_expected",
	"is_low_confidence",
	"verification_status",
)
UPLOAD_FIELD = "requested_documents"
# Document Extraction's Data columns hold 140 characters.
_DATA_LENGTH = 140


def find_request(onboarding_name: str, for_update: bool = False) -> str | None:
	"""The request for an onboarding, if any. There is at most one (unique field, R20)."""
	return frappe.db.get_value(
		REQUEST, {"employee_onboarding": onboarding_name}, "name", for_update=for_update
	)


def enabled_templates() -> list:
	"""`[{name, is_default}]` of the enabled templates, the default first."""
	return frappe.get_all(
		TEMPLATE,
		filters={"is_enabled": 1},
		fields=["name", "is_default"],
		order_by="is_default desc, template_name asc",
	)


def resolve_template(template: str | None) -> str:
	"""The template a Send uses (FR-040): the one named, else the only enabled one."""
	enabled = [row.name for row in enabled_templates()]
	if not enabled:
		raise OnboardingError("no_template")
	if template:
		if template not in enabled:
			raise OnboardingError("template_required")
		return template
	if len(enabled) > 1:
		raise OnboardingError("template_required")
	return enabled[0]


def send_link(onboarding_name: str, config: dict, template: str | None = None) -> dict:
	"""Create or reuse the onboarding's request, snapshot the template's list, mint a link and email it.

	Every refusal happens before the first write.
	"""
	onboarding = frappe.get_doc("Employee Onboarding", onboarding_name)
	if onboarding.docstatus == 2:
		raise OnboardingError("onboarding_cancelled")
	if onboarding.employee:
		raise OnboardingError("already_has_employee")

	applicant = (
		frappe.db.get_value(
			"Job Applicant", onboarding.job_applicant, ["email_id", "applicant_name"], as_dict=True
		)
		or frappe._dict()
	)
	candidate_email = (applicant.email_id or "").strip()
	if not EMAIL.match(candidate_email):
		# A link to the Job Applicant, where the email is added (contracts/hr-actions.md).
		label = (applicant.applicant_name or "").strip() or onboarding.job_applicant
		link = get_link_to_form("Job Applicant", onboarding.job_applicant, frappe.utils.escape_html(label))
		raise OnboardingError("no_email", context={"applicant": link})

	template = resolve_template(template)
	# Every type the template lists may have been disabled since it was saved (M-4).
	if not _enabled_documents(template):
		raise OnboardingError("no_documents", context={"template": template})

	name = find_request(onboarding.name)
	if name:
		request = frappe.get_doc(REQUEST, name)
		if request.status in CLOSED_STATUSES:
			raise OnboardingError("closed", context={"status": request.status})
	else:
		request = _insert_request(onboarding)

	request.flags.via_service = True
	request.job_applicant = onboarding.job_applicant
	request.company = onboarding.company
	request.onboarding_name = onboarding.name
	request.candidate_name = (applicant.applicant_name or "").strip()
	request.candidate_email = candidate_email

	# A new link starts with nothing staged and nothing delivered by it (R9, R10). Done before
	# the snapshot, which drops the rows of types no longer listed, staged uploads and all.
	_clear_staged(request)
	request.template = template
	_snapshot_documents(request, template)
	request.replaced_verification_document_ids = None
	request.link_delivered_on = None

	link = mint_link(request.name)
	sent_on = now_datetime()
	request.link_code_hash = link.code_hash
	request.link_ref = link.ref
	request.link_sent_on = sent_on
	request.link_expires_on = add_days(sent_on, LINK_VALIDITY_DAYS)
	if not request.status:
		request.status = "Link Sent"

	# Saved before the invite goes out, never after (FR-006). The portal resolves a code by
	# its hash, so a candidate who receives the link before the hash is stored holds a URL
	# that can never open. A failed save costs an email that was never sent, which HR can
	# retry, rather than a dead link in a stranger's inbox, which nobody can.
	request.save(ignore_permissions=True)

	url = f"{config['portal_url']}/s/{link.code}"
	email_sent = email.send_link_email(request, url, job_title=onboarding.designation)
	request.db_set("link_emailed", 1 if email_sent else 0)

	log_event(
		"link_sent",
		request=request.name,
		onboarding=onboarding.name,
		status=request.status,
		count=len(requested_rows(request)),
		outcome="emailed" if email_sent else "shown",
	)

	answer = {
		"request": request.name,
		"status": request.status,
		"email_sent": email_sent,
		"expires_on": request.link_expires_on,
	}
	if not email_sent:
		# Returned so HR can hand the link over when the email did not go out (FR-007).
		answer["link"] = url
	return answer


def _insert_request(onboarding):
	"""Insert the onboarding's request, or load the one a racing Send just inserted (R20).

	The unique `employee_onboarding` is the only guard. On MariaDB Frappe reports a unique-key
	violation as UniqueValidationError (a primary-key one as DuplicateEntryError); both mean
	another Send got there first, so this one becomes a resend of that request.
	"""
	request = frappe.new_doc(REQUEST)
	request.flags.via_service = True
	request.employee_onboarding = onboarding.name
	request.onboarding_name = onboarding.name
	request.job_applicant = onboarding.job_applicant
	request.company = onboarding.company
	request.status = "Link Sent"
	try:
		request.insert(ignore_permissions=True)
		return request
	except _LOST_RACE:
		# The insert queued a "must be unique" message for the client; this is not an error.
		frappe.clear_messages()
		# A locking read sees the other transaction's committed row; a plain read could
		# still be looking at this transaction's snapshot from before it.
		name = find_request(onboarding.name, for_update=True)
		if not name:
			raise
		existing = frappe.get_doc(REQUEST, name, for_update=True)
		if existing.status in CLOSED_STATUSES:
			raise OnboardingError("closed", context={"status": existing.status})
		return existing


def _enabled_documents(template: str) -> list:
	listed = frappe.get_all(
		"Template Document", filters={"parent": template, "parenttype": TEMPLATE}, pluck="document_type"
	)
	return (
		frappe.get_all(DOCUMENT_TYPE, filters={"name": ("in", listed), "is_enabled": 1}, pluck="name")
		if listed
		else []
	)


def requested_rows(request) -> list:
	"""The rows the current link asks for, without those kept only for an earlier delivery."""
	return [row for row in request.requested_documents if row.is_requested]


def _snapshot_documents(request, template: str):
	"""Rebuild `requested_documents` from the template's list, in its order (FR-008).

	A row already on the request for the same document type is reused, so whatever the
	last delivery left on it stays until the next delivery replaces it (R9). A row of a type
	the template no longer lists is kept, not requested, while it holds a delivered file: the
	delivery stands until the next one replaces it, files and all. Any other such row is dropped.
	"""
	existing = {row.document_type: row for row in request.requested_documents}
	rows = []
	asked = set()
	for listed in frappe.get_doc(TEMPLATE, template).documents:
		doc_type = frappe.db.get_value(
			DOCUMENT_TYPE,
			listed.document_type,
			[
				"document_code",
				"category",
				"default_allowed_file_types",
				"default_max_file_size_mb",
				"help_text",
				"is_enabled",
			],
			as_dict=True,
		)
		# A type disabled since the list was saved is not asked for.
		if not doc_type or not doc_type.is_enabled:
			continue
		values = {
			"document_type": listed.document_type,
			"document_code": doc_type.document_code,
			"is_mandatory": listed.is_mandatory,
			"allowed_file_types": listed.allowed_file_types or doc_type.default_allowed_file_types,
			"max_file_size_mb": listed.max_file_size_mb or doc_type.default_max_file_size_mb,
			"help_text": listed.help_text or doc_type.help_text,
			"display_group": doc_type.category,
			"is_requested": 1,
		}
		row = existing.get(listed.document_type)
		if row:
			row.update(values)
		rows.append(row or values)
		asked.add(listed.document_type)

	for row in request.requested_documents:
		if row.document_type not in asked and row.file:
			row.is_requested = 0
			rows.append(row)

	request.set("requested_documents", [])
	for idx, row in enumerate(rows, start=1):
		request.append("requested_documents", row).idx = idx


# ---------------------------------------------------------------- staged files (R9)


def _clear_staged(request):
	"""Forget every staged upload and delete its File, unless a delivery promoted it."""
	for row in request.requested_documents:
		if row.staged_file and row.staged_file != row.file:
			_drop_file(request, row.staged_file)
		for field in STAGED_FIELDS:
			row.set(field, None)


def _drop_file(request, file_url: str | None):
	"""Delete one upload File of the request with this URL.

	One File per upload. Frappe gives identical content the same URL, so the count of Files
	for a URL follows the count of uploads, and deleting any one of them is the same.

	The record goes with this transaction; the bytes only once it commits. File.on_trash deletes
	them at once, and a rollback would bring the record back without them.
	"""
	if not file_url or request.is_new():
		return
	name = frappe.db.get_value(
		"File",
		{
			"file_url": file_url,
			"attached_to_doctype": REQUEST,
			"attached_to_name": request.name,
			"attached_to_field": UPLOAD_FIELD,
		},
		"name",
	)
	if not name:
		return
	file_doc = frappe.get_doc("File", name)
	frappe.db.delete("File", {"name": name})
	frappe.db.after_commit.add(functools.partial(_delete_file_bytes, file_doc))


def _delete_file_bytes(file_doc):
	"""After the commit: the bytes, unless another File holds the same content (as File does)."""
	shared = file_doc.content_hash and frappe.db.exists("File", {"content_hash": file_doc.content_hash})
	file_doc.delete_file_data_content(only_thumbnail=bool(shared))


def replaced_ids(request) -> list[str]:
	try:
		ids = json.loads(request.replaced_verification_document_ids or "[]")
	except ValueError:
		return []
	return [i for i in ids if isinstance(i, str) and i] if isinstance(ids, list) else []


def _add_replaced(request, verification_document_id: str | None):
	if not verification_document_id:
		return
	ids = replaced_ids(request)
	if verification_document_id not in ids:
		ids.append(verification_document_id)
	request.replaced_verification_document_ids = json.dumps(ids)


def _empty_staged(request, row):
	_drop_file(request, row.staged_file)
	for field in STAGED_FIELDS:
		row.set(field, None)


# ------------------------------------------------------------------ portal (US2)


def current_link_state(request) -> str:
	return link_state(
		request.status,
		get_datetime(request.link_delivered_on) if request.link_delivered_on else None,
		get_datetime(request.link_expires_on) if request.link_expires_on else None,
		now_datetime(),
	)


def resolve_link(code, for_update: bool = False):
	"""The request a link code belongs to. Anything wrong is the one `link_invalid`.

	`for_update` is for the write paths: the portal sends up to four uploads at once, and each
	saves the whole request. Locked, they queue behind each other instead of failing the save.
	"""
	if not isinstance(code, str) or not code or len(code) > MAX_TOKEN_LENGTH:
		raise OnboardingError("link_invalid")
	rows = frappe.get_all(
		REQUEST,
		filters={"link_code_hash": hash_code(code)},
		fields=["name", "link_code_hash"],
		limit=2,
	)
	if len(rows) != 1 or not codes_match(rows[0].link_code_hash, code):
		raise OnboardingError("link_invalid")
	name = rows[0].name
	frappe.flags[REQUEST_FLAG] = name
	if not for_update:
		return frappe.get_doc(REQUEST, name)

	# The lock waits for the other call's commit, but this transaction's snapshot, taken at its
	# first read, would still serve the child rows from before it (and MariaDB's snapshot
	# isolation refuses a lock on a row changed since). Nothing is written yet, so start over:
	# the locking read takes no snapshot, and the child rows are read after it.
	frappe.db.rollback()
	request = frappe.get_doc(REQUEST, name, for_update=True)
	# A resend may have replaced the code while this call waited.
	if not codes_match(request.link_code_hash, code):
		raise OnboardingError("link_invalid")
	return request


def require_open(request):
	"""Expired, used and revoked links get the same answer as an unknown code (FR-010)."""
	state = current_link_state(request)
	if state != OPEN:
		raise OnboardingError("closed", context={"category": state})


def _row_for(request, document_code):
	"""The requested row for a code. A row kept only for an earlier delivery is not addressable."""
	if not document_code or not isinstance(document_code, str):
		return None
	return next((r for r in requested_rows(request) if r.document_code == document_code), None)


def stage_upload(request, document_code, verification_document_id, content: bytes) -> str:
	"""Stage one upload on its row (R9, R12). Returns the private file URL."""
	require_open(request)
	row = _row_for(request, document_code)
	if not row:
		raise OnboardingError("unknown_document")

	kind = filetype.guess(content) if content else None
	problem = check_upload(
		content, kind.extension if kind else None, row.allowed_file_types, row.max_file_size_mb
	)
	if problem:
		raise OnboardingError(problem)

	verification_document_id = verification_document_id or None
	if (
		row.staged_verification_document_id
		and row.staged_verification_document_id != verification_document_id
	):
		_add_replaced(request, row.staged_verification_document_id)

	# A 9thSense document filed in another row moves to this one.
	if verification_document_id:
		for other in request.requested_documents:
			if other is not row and other.staged_verification_document_id == verification_document_id:
				_empty_staged(request, other)

	_drop_file(request, row.staged_file)

	# Named after the document and what the bytes are, never what the candidate called them: a
	# scan named after its Aadhaar number would store the number (FR-012).
	file_name = f"{row.document_code}.{kind.extension}"

	# Private and attached in the same insert: attaching afterwards leaves a window in which
	# the File exists with no permission scope at all.
	try:
		file_doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"content": content,
				"is_private": 1,
				"attached_to_doctype": REQUEST,
				"attached_to_name": request.name,
				"attached_to_field": UPLOAD_FIELD,
			}
		).insert(ignore_permissions=True)
	except MaxFileSizeReachedError:
		raise OnboardingError("file_size") from None
	except frappe.ValidationError:
		# File's own content checks: an extension the site does not allow, a PDF with scripts.
		raise OnboardingError("file_type") from None

	row.staged_file = file_doc.file_url
	row.staged_file_name = file_name
	row.staged_file_size_bytes = len(content)
	row.staged_verification_document_id = verification_document_id
	row.staged_on = now_datetime()
	request.flags.via_service = True
	request.save(ignore_permissions=True)
	return file_doc.file_url


def discard_upload(request, verification_document_id):
	"""The candidate dropped an upload: empty any staged row holding it, and remember the id."""
	require_open(request)
	if not verification_document_id or not isinstance(verification_document_id, str):
		raise OnboardingError("unknown_document")
	for row in request.requested_documents:
		if row.staged_verification_document_id == verification_document_id:
			_empty_staged(request, row)
	_add_replaced(request, verification_document_id)
	request.flags.via_service = True
	request.save(ignore_permissions=True)


def accept_delivery(request, payload):
	"""Store a completion, then derive the extraction rows from it (R17, FR-013, FR-014).

	The checks run in the contract's order. The bundle is committed before anything is
	derived from it, so a failure in the derivation cannot take it.
	"""
	state = current_link_state(request)
	delivered_by_this_link = state == SUBMITTED and bool(request.link_delivered_on)
	if request.status not in RECEIVING_STATUSES or not (state == OPEN or delivered_by_this_link):
		raise OnboardingError("closed", context={"category": state})
	if not isinstance(payload, dict):
		raise OnboardingError("schema", context={"pointer": "/"})
	if payload.get("ref") != request.link_ref:
		raise OnboardingError("stale_ref")
	validate_completion(payload)

	# Masked before anything is stored or logged (FR-012).
	payload = mask_payload(payload)
	step = document_step(payload)
	received_on = now_datetime()

	request.flags.via_service = True
	request.verification_response = json.dumps(payload, indent=2, default=str)
	request.documents_received_on = received_on
	request.verification_case_id = (step.get("provider") or {}).get("session_id")
	request.verification_result = verification_result(payload)
	request.extraction_error = None

	# Per-document results, matched by document_code. A delivery replaces them as a whole.
	for row in request.requested_documents:
		for field in RESULT_FIELDS:
			row.set(field, None)
	unmatched = 0
	for entry in step.get("documents") or []:
		row = _row_for(request, entry.get("document_code"))
		if not row:
			unmatched += 1
			continue
		row.detected_document_type = (entry.get("detected_document_type") or "")[:_DATA_LENGTH] or None
		row.is_detected_type_expected = 1 if entry.get("is_detected_type_expected") else 0
		row.is_low_confidence = 1 if entry.get("low_confidence") else 0
		# As received (FR-017): a review or unreadable status is not ours to round to a verdict.
		status = entry.get("status")
		row.verification_status = str(status)[:_DATA_LENGTH] if status not in (None, "") else None
	if unmatched:
		log_event("delivery_unmatched", request=request.name, count=unmatched)

	# The delivered set is replaced as a whole: rows kept only for the earlier delivery go, files
	# and all (R9).
	for row in [r for r in request.requested_documents if not r.is_requested]:
		_drop_file(request, row.file)
		request.remove(row)
	for idx, row in enumerate(request.requested_documents, start=1):
		row.idx = idx

	# This link's uploads become the delivered files; a row with nothing staged is emptied.
	# Staged fields stay, so a retry of the same delivery promotes the same files again.
	for row in request.requested_documents:
		retry_of_same_file = delivered_by_this_link and row.file and row.file == row.staged_file
		if row.file and not retry_of_same_file:
			_drop_file(request, row.file)
		row.file = row.staged_file or None
		row.file_name = row.staged_file_name if row.staged_file else None
		row.file_size_bytes = row.staged_file_size_bytes if row.staged_file else 0
		row.verification_document_id = row.staged_verification_document_id if row.staged_file else None

	request.link_delivered_on = received_on
	request.status = "Data Received"
	request.save(ignore_permissions=True)
	# The bundle is the only copy Frappe will ever receive; the rollback below must not take it.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit -- the bundle is the only copy and step 8's rollback must not take it

	count = 0
	try:
		# The commit let the lock go. A call that slipped in since fails this save, which is
		# noted below like any other derivation failure.
		frappe.db.get_value(REQUEST, request.name, "name", for_update=True)
		request.set("extractions", [])
		for code, key, value in extraction_rows(step):
			request.append(
				"extractions",
				{"document_code": code[:_DATA_LENGTH], "key": key[:_DATA_LENGTH], "value": value},
			)
		request.flags.via_service = True
		request.save(ignore_permissions=True)
		count = len(request.extractions)
	except Exception as exc:
		frappe.db.rollback()
		frappe.db.set_value(
			REQUEST,
			request.name,
			"extraction_error",
			_("The values could not be read from the delivery. It is stored; see the Error Log."),
			update_modified=False,
		)
		log_failure("Document collection: extraction failed", "extraction", exc=exc, request=request.name)
		# No commit: the request's normal commit keeps this note, as the handler returns normally.

	log_event(
		"delivery_accepted",
		request=request.name,
		status=request.status,
		count=count,
		outcome="retry" if delivered_by_this_link else "first",
	)


# ------------------------------------------------------------- onboarding lifecycle (R18)


def cancel_for_onboarding(onboarding_name: str, deleted: bool):
	"""The onboarding was cancelled or deleted: close its request's link.

	Completed stays Completed. On delete, the request lets go of the onboarding so the delete is
	not blocked by the link, and keeps its name in `onboarding_name`.
	"""
	name = find_request(onboarding_name, for_update=True)
	if not name:
		return
	request = frappe.get_doc(REQUEST, name)
	request.flags.via_service = True
	if request.status not in CLOSED_STATUSES:
		request.status = "Cancelled"
	if deleted:
		request.onboarding_name = request.onboarding_name or onboarding_name
		request.employee_onboarding = None
	request.save(ignore_permissions=True)
	log_event(
		"onboarding_closed",
		request=request.name,
		onboarding=onboarding_name,
		status=request.status,
		outcome="deleted" if deleted else "cancelled",
	)


# ------------------------------------------------------------- Create Employee (US3)


def resolve_link_value(doctype: str, value: str, company: str | None = None) -> str | None:
	"""The existing record a link value names, or None (R6). Never inserts.

	The name match is case-insensitive (MariaDB collation) and returns the stored name. A
	doctype with a company field (Department) is matched within the onboarding's company only,
	by name or by its `<doctype>_name` title.
	"""
	if not doctype or not isinstance(value, str) or not value.strip():
		return None
	value = value.strip()
	meta = frappe.get_meta(doctype)
	if company and meta.has_field("company"):
		attempts = [{"name": value, "company": company}]
		title = f"{frappe.scrub(doctype)}_name"
		if meta.has_field(title):
			attempts.append({title: value, "company": company})
	else:
		attempts = [{"name": value}]
	for filters in attempts:
		name = frappe.db.get_value(doctype, filters, "name")
		if name:
			return name
	return None


def _spec(df, child_fields=()) -> FieldSpec:
	return FieldSpec(
		fieldname=df.fieldname,
		label=df.label or df.fieldname,
		fieldtype=df.fieldtype,
		options=df.options,
		length=df.length or None,
		child_fields=tuple(child_fields),
	)


def employee_field_specs(rows) -> list[FieldSpec]:
	"""FieldSpecs for the Employee fields the mapping `rows` write, from this site's metadata."""
	meta = frappe.get_meta("Employee")
	tables: dict = {}
	plain: list = []
	for key, _primary, _fallback in rows:
		entry = get_entry(key)
		if entry is None:
			continue
		if entry.target_child_table:
			tables.setdefault(entry.target_child_table, []).append(entry.target_field)
		else:
			plain.append(entry.target_field)

	if BANK_FIELDS & set(plain):
		# Not a mapped field: plan_fill sets it to Bank when it fills bank details.
		plain.append(SALARY_MODE)
	specs = [_spec(df) for df in (meta.get_field(f) for f in plain) if df]
	for table, child_fieldnames in tables.items():
		df = meta.get_field(table)
		if not df or df.fieldtype != "Table":
			continue
		child_meta = frappe.get_meta(df.options)
		children = [_spec(c) for c in (child_meta.get_field(f) for f in child_fieldnames) if c]
		specs.append(_spec(df, children))
	return specs


def mapping_rows(template: str | None) -> list[tuple]:
	"""The template's mapping as it stands now, as `(field_key, source_code, fallback_code)` (R24).

	Read live, not snapshotted: a mapping HR corrects applies to requests already sent. A request
	sent before templates existed has none, and reads the default template's.
	"""
	template = template or frappe.db.get_value(TEMPLATE, {"is_default": 1}, "name")
	if not template or not frappe.db.exists(TEMPLATE, template):
		return []
	code_of = dict(frappe.get_all(DOCUMENT_TYPE, fields=["name", "document_code"], as_list=True))
	return [
		(row.field_key, code_of.get(row.source_document), code_of.get(row.fallback_document))
		for row in frappe.get_doc(TEMPLATE, template).field_mapping
		if code_of.get(row.source_document)
	]


def fill_employee(employee_doc, onboarding_name: str) -> dict | None:
	"""Fill the unsaved Employee from the onboarding's request, and write the report (R3, R4).

	None when there is no request or it is closed: only the native behaviour applies. A request
	still waiting for the candidate answers `{"state": "no_data"}` and fills nothing.
	"""
	name = find_request(onboarding_name)
	if not name:
		return None
	request = frappe.get_doc(REQUEST, name)
	if request.status in CLOSED_STATUSES:
		return None
	if request.status == "Link Sent":
		return {"state": "no_data", "request": request.name}

	rows = mapping_rows(request.template)
	if not rows:
		# No template mapping to read (M-5): say so rather than report "Filled 0".
		return {"state": "no_mapping", "request": request.name}
	fields = employee_field_specs(rows)
	current = {}
	for spec in fields:
		value = employee_doc.get(spec.fieldname)
		current[spec.fieldname] = len(value or []) if spec.fieldtype == "Table" else value
	# What the name parts would rebuild on save; a different name is reported, not filled (R4).
	current[EMPLOYEE_NAME] = employee_doc.get(EMPLOYEE_NAME)
	candidates = candidates_from(
		[(row.document_code, row.key, row.value) for row in request.extractions], rows
	)
	company = employee_doc.get("company") or request.company
	plan = plan_fill(fields, current, candidates, resolve_link_value, company)

	for fieldname, value in plan.values.items():
		employee_doc.set(fieldname, value)
	for table, new_rows in plan.child_rows.items():
		for row in new_rows:
			employee_doc.append(table, row)

	# Replaced as a whole at each Create Employee (FR-024). Nothing else on the request changes,
	# so Create Employee can be repeated while the Employee is unsaved (FR-027).
	request.set("fill_results", [])
	for row in plan.report:
		request.append("fill_results", asdict(row))
	request.last_fill_on = now_datetime()
	request.flags.via_service = True
	request.save(ignore_permissions=True)

	filled = sum(1 for row in plan.report if row.outcome == FILLED)
	skipped = sum(1 for row in plan.report if row.outcome in (ALREADY_FILLED, INVALID))
	log_event("employee_filled", request=request.name, onboarding=onboarding_name, count=filled)
	return {
		"state": "filled",
		"request": request.name,
		"filled": filled,
		"skipped": skipped,
		"verification_result": request.verification_result,
		"name_mismatch": plan.name_mismatch,
		# Resent after the delivery: the data is the earlier link's, and saving closes the new one.
		"newer_link_open": not request.link_delivered_on,
	}


def complete_for_employee(employee):
	"""The Employee was saved: link it, complete the request and attach the files (R19, FR-026).

	Never raises, so the Employee save stands whatever happens here.
	"""
	savepoint = "nso_complete_for_employee"
	request_name = None
	try:
		frappe.db.savepoint(savepoint)
		names = frappe.get_all(
			REQUEST,
			filters={"job_applicant": employee.job_applicant, "status": ("in", RECEIVING_STATUSES)},
			pluck="name",
			order_by="modified desc",
			limit=1,
		)
		if not names:
			return
		request_name = names[0]
		request = frappe.get_doc(REQUEST, request_name, for_update=True)
		request.flags.via_service = True
		request.employee = employee.name
		request.status = "Completed"

		failed = 0
		for row in request.requested_documents:
			if not row.file:
				continue
			reason = _attach_to_employee(request.name, row, employee.name)
			if reason:
				failed += 1
				request.append(
					"fill_results",
					{
						"outcome": ATTACH_FAILED,
						"field_label": row.document_type or row.document_code,
						"fieldname": row.document_code,
						"reason": reason,
					},
				)
		request.save(ignore_permissions=True)
		log_event(
			"request_completed",
			request=request.name,
			employee=employee.name,
			status=request.status,
			count=failed,
		)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		log_failure(
			"Document collection: completing the request failed",
			"complete",
			request=request_name,
			employee=employee.name,
		)


def _attach_to_employee(request_name: str, row, employee_name: str) -> str | None:
	"""Attach one delivered file to the Employee by its URL (no copy of the bytes).

	Returns None, or a short reason when it failed. A failure is rolled back on its own and its
	desk message dropped, so the Employee save still reads as a success.
	"""
	savepoint = "nso_attach_file"
	messages = len(getattr(frappe.local, "message_log", None) or [])
	try:
		frappe.db.savepoint(savepoint)
		frappe.get_doc(
			{
				"doctype": "File",
				"file_url": row.file,
				"file_name": row.file_name,
				"is_private": 1,
				"attached_to_doctype": "Employee",
				"attached_to_name": employee_name,
			}
		).insert(ignore_permissions=True)
		return None
	except Exception as exc:
		frappe.db.rollback(save_point=savepoint)
		if getattr(frappe.local, "message_log", None):
			del frappe.local.message_log[messages:]
		log_failure(
			"Document collection: attach failed", "attach", request=request_name, employee=employee_name
		)
		return _("Could not attach the file ({0}).").format(type(exc).__name__)

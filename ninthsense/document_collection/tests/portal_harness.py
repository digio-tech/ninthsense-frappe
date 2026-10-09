"""Shared set-up for the portal integration tests: a sent link, and calls through
frappe.handler.execute_cmd at the addresses the portal calls, as Guest.

The handlers commit (store first, R17) and roll back (every refusal). Here a commit moves a
savepoint and a rollback returns to it, so the store-first behaviour is still observable and
the class-level rollback still removes everything.
"""

import hashlib
import hmac
import json
import struct
import time
import zlib
from io import BytesIO
from pathlib import Path
from unittest import mock

import frappe
import frappe.app
import frappe.handler
import frappe.utils.error
from frappe.utils import today
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from ninthsense import install
from ninthsense.core.callback_signature import SIGNATURE_HEADER
from ninthsense.document_collection import service
from ninthsense.document_collection.tests.error_logs import AppTestCase

PORTAL_URL = "http://localhost:3000"
SECRET = "cd" * 32
REQUEST = "Document Collection Request"
OLD = "ninthsense.document_collection.portal_api."
SAVEPOINT = "nso_portal_test"
FIXTURE = Path(__file__).resolve().parents[2] / "core" / "tests" / "fixtures" / "completion-mock.json"


def png_bytes(seed: int = 0) -> bytes:
	"""A real 1x1 PNG; `seed` changes the pixel so the content hash differs."""

	def chunk(kind, data):
		body = kind + data
		return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

	ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
	raw = b"\x00" + bytes([seed % 256, (seed // 256) % 256, 7])
	return (
		b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
	)


def sign(raw: bytes, secret: str = SECRET, t: int | None = None) -> str:
	t = int(time.time()) if t is None else t
	digest = hmac.new(secret.encode(), f"{t}.".encode() + raw, hashlib.sha256).hexdigest()
	return f"t={t},v1={digest}"


class Answer:
	def __init__(self, status, message):
		self.status = status
		self.message = message

	def __repr__(self):
		return f"Answer({self.status}, {self.message!r})"


class PortalTestCase(AppTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		install.after_install()
		settings = frappe.get_single("Document Collection Settings")
		settings.portal_url = PORTAL_URL
		settings.callback_secret = SECRET
		settings.save(ignore_permissions=True)
		for name in frappe.get_all("Email Account", filters={"default_outgoing": 1}, pluck="name"):
			frappe.db.set_value("Email Account", name, "default_outgoing", 0)
		cls.company = frappe.get_all("Company", pluck="name", limit=1)[0]
		if not frappe.db.exists("Designation", "Engineer"):
			frappe.get_doc({"doctype": "Designation", "designation_name": "Engineer"}).insert()

	def setUp(self):
		frappe.set_user("Administrator")
		self.onboarding = self.make_onboarding()
		self.code = self.send(self.onboarding.name)
		self.request_name = service.find_request(self.onboarding.name)
		frappe.db.savepoint(SAVEPOINT)
		real_rollback = frappe.db.rollback

		def fake_commit(*args, **kwargs):
			frappe.db.savepoint(SAVEPOINT)

		def fake_rollback(*args, save_point=None, **kwargs):
			real_rollback(save_point=save_point or SAVEPOINT)

		for name, fake in (("commit", fake_commit), ("rollback", fake_rollback)):
			patcher = mock.patch.object(frappe.db, name, side_effect=fake)
			patcher.start()
			self.addCleanup(patcher.stop)

		# Frappe's error snapshot defers its insert to a queue; here it is inserted at once, so a
		# test can read it and the class rollback removes it.
		real_log_error = frappe.utils.error.log_error

		def log_error_now(*args, defer_insert=False, **kwargs):
			return real_log_error(*args, **kwargs)

		patcher = mock.patch.object(frappe.utils.error, "log_error", side_effect=log_error_now)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request = None
		frappe.local.form_dict = frappe._dict()

	# ----------------------------------------------------------------- set-up

	def make_onboarding(self, name="Asha Rani Verma"):
		applicant = frappe.get_doc(
			{
				"doctype": "Job Applicant",
				"applicant_name": name,
				"email_id": f"candidate-{frappe.generate_hash(length=8)}@example.com",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
		offer = frappe.get_doc(
			{
				"doctype": "Job Offer",
				"job_applicant": applicant.name,
				"applicant_name": applicant.applicant_name,
				"offer_date": today(),
				"designation": "Engineer",
				"company": self.company,
				"status": "Awaiting Response",
			}
		).insert(ignore_permissions=True)
		return frappe.get_doc(
			{
				"doctype": "Employee Onboarding",
				"job_applicant": applicant.name,
				"job_offer": offer.name,
				"company": self.company,
				"designation": "Engineer",
				"date_of_joining": today(),
				"boarding_begins_on": today(),
			}
		).insert(ignore_permissions=True)

	def send(self, onboarding_name) -> str:
		"""Send (or resend) as Administrator and return the new link code."""
		user = frappe.session.user
		frappe.set_user("Administrator")
		try:
			answer = service.send_link(onboarding_name, {"portal_url": PORTAL_URL})
		finally:
			frappe.set_user(user)
		self.commit()
		return answer["link"].rsplit("/s/", 1)[1]

	def commit(self):
		"""What the end of an HR request would do: a later refusal's rollback keeps this."""
		frappe.db.savepoint(SAVEPOINT)

	def request(self):
		return frappe.get_doc(REQUEST, self.request_name)

	# ------------------------------------------------------------------ calls

	def call(self, method, http="POST", form=None, data=None, files=None, headers=None):
		"""One portal call at the old address, as Guest. Returns an Answer."""
		builder_args = {"method": http, "path": f"/api/method/{OLD}{method}", "headers": headers or {}}
		if files is not None:
			builder_args["data"] = {**(form or {}), **files}
		elif data is not None:
			builder_args["data"] = data
			builder_args["content_type"] = "application/json"
		elif http == "GET":
			builder_args["query_string"] = form or {}
		else:
			builder_args["data"] = form or {}
		# set_user empties form_dict, so it goes first.
		frappe.set_user("Guest")
		frappe.local.request = Request(EnvironBuilder(**builder_args).get_environ())
		frappe.local.form_dict = frappe._dict(form or {})
		frappe.local.response = frappe._dict()
		try:
			result = frappe.handler.execute_cmd(OLD + method)
			if http == "POST":
				# Frappe commits a POST that returns.
				frappe.db.commit()
			return Answer(200, result)
		except Exception as exc:
			# What a real request does with it: the status is the one HTTP sends.
			self.last_exception = exc
			self.form_dict_at_error = dict(frappe.local.form_dict)
			response = frappe.app.handle_exception(exc)
			return Answer(response.status_code, str(exc))
		finally:
			frappe.set_user("Administrator")

	def get_request(self, code=None):
		return self.call("get_request", http="GET", form={"token": code or self.code})

	def upload(self, document_code, content, filename="scan.png", vdid=None, code=None):
		form = {"token": code or self.code, "document_code": document_code}
		if vdid:
			form["verification_document_id"] = vdid
		return self.call("store_document", form=form, files={"file": (BytesIO(content), filename)})

	def discard(self, vdid, code=None):
		return self.call(
			"discard_document", form={"token": code or self.code, "verification_document_id": vdid}
		)

	def deliver(self, payload, code=None, secret=SECRET, t=None, raw=None):
		token = code or self.code
		raw = raw if raw is not None else json.dumps({"token": token, "payload": payload}).encode()
		return self.call(
			"store_verification",
			form={"token": token, "payload": payload},
			data=raw,
			headers={SIGNATURE_HEADER: sign(raw, secret, t)},
		)

	# --------------------------------------------------------------- payloads

	def completion(self, codes=None):
		"""The fixture, for this request's current link and staged ids."""
		payload = json.loads(FIXTURE.read_text())
		request = self.request()
		payload["ref"] = request.link_ref
		payload["x-hrms"] = {"application": request.name}
		step = payload["steps"][0]
		staged = {r.document_code: r.staged_verification_document_id for r in request.requested_documents}
		if codes is not None:
			step["documents"] = [d for d in step["documents"] if d["document_code"] in codes]
		for document in step["documents"]:
			if staged.get(document["document_code"]):
				document["verification_document_id"] = staged[document["document_code"]]
		return payload

	def error_logs(self, text):
		return frappe.get_all("Error Log", filters={"method": ("like", f"%{text}%")}, pluck="name")

"""US2 end to end: the four guest handlers at the addresses the portal calls (T043)."""

import json
import os
import time
import traceback
from unittest import mock

import frappe
from frappe.utils import add_days, now_datetime

from ninthsense.core.config import GENERIC_ERROR
from ninthsense.core.contract.validate import validate_request
from ninthsense.document_collection import service
from ninthsense.document_collection.tests.portal_harness import (
	REQUEST,
	PortalTestCase,
	png_bytes,
)

# Rows whose allowed types include png in the seeded list.
IMAGE_CODES = ("aadhaar_front", "pan_card", "graduation_certificate", "cancelled_cheque")


def _files_of(request_name):
	return frappe.get_all(
		"File",
		filters={"attached_to_doctype": REQUEST, "attached_to_name": request_name},
		fields=["name", "file_url", "is_private"],
	)


class TestPortalApi(PortalTestCase):
	def stage_all(self):
		for i, code in enumerate(IMAGE_CODES):
			answer = self.upload(code, png_bytes(i + 1), vdid=f"doc-{code}")
			self.assertEqual(answer.status, 200, answer)

	# (a)
	def test_get_request_returns_a_valid_descriptor(self):
		answer = self.get_request()
		self.assertEqual(answer.status, 200, answer)
		descriptor = answer.message
		validate_request(descriptor)
		request = self.request()
		self.assertEqual(descriptor["ref"], request.link_ref)
		self.assertEqual(descriptor["state"], "open")
		self.assertEqual(descriptor["subject"], {"display_name": "Asha"})
		self.assertEqual(descriptor["x-hrms"], {"application": request.name})
		self.assertEqual(
			[d["document_code"] for d in descriptor["steps"][0]["documents"]],
			[r.document_code for r in request.requested_documents],
		)

	# (b)
	def test_unknown_and_malformed_codes_get_one_404(self):
		for code in ("not-a-real-code", "x" * 129):
			answer = self.get_request(code=code)
			self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))

	# (b2)
	def test_expired_and_cancelled_links_get_the_closed_descriptor(self):
		expired_onboarding = self.make_onboarding()
		expired_code = self.send(expired_onboarding.name)
		frappe.db.set_value(
			REQUEST,
			service.find_request(expired_onboarding.name),
			"link_expires_on",
			add_days(now_datetime(), -1),
		)
		self.commit()

		cancelled_onboarding = self.make_onboarding()
		cancelled_code = self.send(cancelled_onboarding.name)
		service.cancel_for_onboarding(cancelled_onboarding.name, deleted=False)
		self.commit()

		for code, state in ((expired_code, "expired"), (cancelled_code, "revoked")):
			answer = self.get_request(code=code)
			self.assertEqual(answer.status, 200, answer)
			self.assert_closed_descriptor(answer.message, state)

	def assert_closed_descriptor(self, descriptor, state):
		validate_request(descriptor)
		self.assertEqual(descriptor["state"], state)
		self.assertEqual(descriptor["steps"][0]["documents"], [])
		for key in ("subject", "features", "x-hrms"):
			self.assertNotIn(key, descriptor)
		self.assertNotIn("replaced_verification_document_ids", descriptor["steps"][0])
		for key in ("ref", "hrms", "goal_key", "stage", "catalogue_version", "completion", "branding"):
			self.assertIn(key, descriptor)

	# M16: our own descriptor drift is answered like a bad code, but logged.
	def test_a_descriptor_that_fails_its_schema_is_logged(self):
		drift = {"error": ("like", "%category=descriptor_schema%")}
		before = frappe.db.count("Error Log", drift)
		with mock.patch("ninthsense.document_collection.portal_api.build_descriptor", return_value={"x": 1}):
			answer = self.get_request()
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))
		self.assertEqual(frappe.db.count("Error Log", drift), before + 1)

	def test_closed_links_still_refuse_uploads(self):
		onboarding = self.make_onboarding()
		code = self.send(onboarding.name)
		service.cancel_for_onboarding(onboarding.name, deleted=False)
		self.commit()
		answer = self.upload("aadhaar_front", png_bytes(1), vdid="doc-x", code=code)
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))

	# (c)
	def test_store_document_stages_a_real_png_and_refuses_html(self):
		answer = self.upload("aadhaar_front", png_bytes(), filename="front.pdf", vdid="doc-1")
		self.assertEqual(answer.status, 200, answer)
		self.assertTrue(answer.message["ok"])
		row = next(r for r in self.request().requested_documents if r.document_code == "aadhaar_front")
		self.assertEqual(row.staged_file, answer.message["file_url"])
		self.assertTrue(row.staged_file.startswith("/private/files/"))
		self.assertEqual(row.staged_file_name, "aadhaar_front.png")
		self.assertEqual(row.staged_verification_document_id, "doc-1")
		self.assertFalse(row.file)
		files = _files_of(self.request_name)
		self.assertEqual(len(files), 1)
		self.assertEqual(files[0].is_private, 1)

		html = b"<!doctype html><html><body>not a scan</body></html>"
		refused = self.upload("pan_card", html, filename="pan.jpg")
		self.assertEqual((refused.status, refused.message), (417, "This file type is not accepted."))
		self.assertEqual(len(_files_of(self.request_name)), 1)

	# I3: the candidate's file name is never stored.
	def test_a_file_named_after_an_aadhaar_number_is_stored_under_the_document_code(self):
		answer = self.upload("aadhaar_front", png_bytes(3), filename="Aadhaar 1234 5678 9012.png", vdid="d")
		self.assertEqual(answer.status, 200, answer)
		row = next(r for r in self.request().requested_documents if r.document_code == "aadhaar_front")
		self.assertEqual(row.staged_file_name, "aadhaar_front.png")
		(file_doc,) = frappe.get_all(
			"File",
			filters={"attached_to_doctype": REQUEST, "attached_to_name": self.request_name},
			fields=["file_name", "file_url"],
		)
		stored = frappe.as_json([file_doc, row.as_dict()])
		for digits in ("1234 5678 9012", "123456789012"):
			self.assertNotIn(digits, stored)
		self.assertTrue(file_doc.file_name.startswith("aadhaar_front"))

	def test_store_document_other_refusals(self):
		self.assertEqual(
			(lambda a: (a.status, a.message))(self.upload("payslip_x", png_bytes())),
			(417, "Unknown document."),
		)
		self.assertEqual(
			(lambda a: (a.status, a.message))(self.upload("aadhaar_front", b"")),
			(417, "No file was received."),
		)
		# Resume accepts pdf only.
		self.assertEqual(
			(lambda a: (a.status, a.message))(self.upload("resume", png_bytes())),
			(417, "This file type is not accepted."),
		)

	def test_reupload_replaces_the_staged_copy_and_moves_an_id(self):
		self.upload("aadhaar_front", png_bytes(1), vdid="doc-1")
		self.upload("aadhaar_front", png_bytes(2), vdid="doc-2")
		request = self.request()
		self.assertEqual(json.loads(request.replaced_verification_document_ids), ["doc-1"])
		self.assertEqual(len(_files_of(self.request_name)), 1)

		# doc-2 filed under PAN instead: it leaves the Aadhaar row.
		self.upload("pan_card", png_bytes(2), vdid="doc-2")
		rows = {r.document_code: r for r in self.request().requested_documents}
		self.assertFalse(rows["aadhaar_front"].staged_file)
		self.assertEqual(rows["pan_card"].staged_verification_document_id, "doc-2")
		self.assertEqual(len(_files_of(self.request_name)), 1)

	# I4: concurrent uploads queue behind the request's lock instead of failing the save.
	def test_the_write_paths_lock_the_request_and_the_read_does_not(self):
		real_get_doc = frappe.get_doc
		locked = []

		def spy(*args, **kwargs):
			# Only the load the call starts from: Document.save also locks, but only when saving.
			if args and args[0] == REQUEST and "resolve_link" in [f.name for f in traceback.extract_stack()]:
				locked.append(bool(kwargs.get("for_update")))
			return real_get_doc(*args, **kwargs)

		with mock.patch.object(frappe, "get_doc", side_effect=spy):
			self.assertEqual(self.get_request().status, 200)
			self.assertEqual(locked, [False])
			self.stage_all()
			self.assertEqual(self.discard("doc-pan_card").status, 200)
		payload = self.completion()
		with mock.patch.object(frappe, "get_doc", side_effect=spy):
			self.assertEqual(self.deliver(payload).status, 200)
		self.assertEqual(locked, [False] + [True] * (len(IMAGE_CODES) + 2))

	# M9: a failed call must not take the bytes of a file its rollback brings back.
	def test_a_rolled_back_replacement_keeps_the_earlier_file_on_disk(self):
		from frappe.core.doctype.file.file import File

		self.upload("aadhaar_front", png_bytes(41), vdid="doc-1")
		(first,) = _files_of(self.request_name)
		path = frappe.get_doc("File", first.name).get_full_path()
		real_insert = File.insert

		def failing(file_doc, *args, **kwargs):
			if file_doc.attached_to_name == self.request_name:
				raise RuntimeError("disk full")
			return real_insert(file_doc, *args, **kwargs)

		with mock.patch.object(File, "insert", failing):
			answer = self.upload("aadhaar_front", png_bytes(42), vdid="doc-2")
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))
		self.assertEqual([f.name for f in _files_of(self.request_name)], [first.name])
		self.assertTrue(os.path.exists(path))

		# Committed, the replaced file's bytes go.
		frappe.db.after_commit.reset()
		self.upload("aadhaar_front", png_bytes(43), vdid="doc-3")
		self.assertTrue(os.path.exists(path))
		frappe.db.after_commit.run()
		self.assertFalse(os.path.exists(path))

	# (d)
	def test_discard_document_empties_the_row_and_records_the_id(self):
		self.upload("aadhaar_front", png_bytes(), vdid="doc-1")
		answer = self.discard("doc-1")
		self.assertEqual((answer.status, answer.message), (200, {"ok": True}))
		request = self.request()
		row = next(r for r in request.requested_documents if r.document_code == "aadhaar_front")
		for field in service.STAGED_FIELDS:
			self.assertFalse(row.get(field), field)
		self.assertEqual(json.loads(request.replaced_verification_document_ids), ["doc-1"])
		self.assertEqual(_files_of(self.request_name), [])

		descriptor = self.get_request().message
		self.assertEqual(descriptor["steps"][0]["replaced_verification_document_ids"], ["doc-1"])

	# (e)
	def test_bad_signatures_get_401(self):
		payload = self.completion()
		bad = self.deliver(payload, secret="ef" * 32)
		self.assertEqual((bad.status, bad.message), (401, GENERIC_ERROR))
		self.assertTrue(self.error_logs("CALLBACK SIGNATURE REJECTED (bad_digest)"))

		stale = self.deliver(payload, t=int(time.time()) - 600)
		self.assertEqual((stale.status, stale.message), (401, GENERIC_ERROR))
		self.assertTrue(self.error_logs("CALLBACK SIGNATURE REJECTED (stale_timestamp)"))

		# Checked before the code: a bad signature with an unknown code is still a 401.
		unknown = self.deliver(payload, code="not-a-real-code", secret="ef" * 32)
		self.assertEqual(unknown.status, 401)

		self.assertEqual(self.request().status, "Link Sent")

	# (f)
	def test_a_valid_delivery_is_stored_masked_and_flattened(self):
		self.stage_all()
		answer = self.deliver(self.completion())
		self.assertEqual((answer.status, answer.message), (200, {"ok": True}))

		request = self.request()
		self.assertEqual(request.status, "Data Received")
		self.assertTrue(request.link_delivered_on)
		self.assertTrue(request.documents_received_on)
		self.assertEqual(request.verification_result, "Passed")
		self.assertTrue(request.verification_case_id.startswith("mock_"))
		self.assertIn("XXXX XXXX 7777", request.verification_response)
		self.assertNotIn("999988887777", request.verification_response)
		self.assertFalse(request.extraction_error)

		rows = {r.document_code: r for r in request.requested_documents}
		for code in IMAGE_CODES:
			self.assertEqual(rows[code].file, rows[code].staged_file)
			self.assertEqual(rows[code].verification_document_id, f"doc-{code}")
			self.assertEqual(rows[code].verification_status, "done")
			self.assertTrue(rows[code].is_detected_type_expected)
		self.assertFalse(rows["resume"].file)

		values = {(e.document_code, e.key): e.value for e in request.extractions}
		self.assertEqual(values[("aadhaar_front", "aadhaar_number")], "XXXX XXXX 7777")
		self.assertEqual(values[("pan_card", "pan_number")], "ABCPV1234F")
		self.assertEqual(values[("resume", "current_employer")], "Digio India")
		self.assertNotIn("999988887777", frappe.as_json([e.as_dict() for e in request.extractions]))

		# The link is used: the page gets the closed descriptor, with nothing to collect.
		used = self.get_request()
		self.assertEqual(used.status, 200, used)
		self.assert_closed_descriptor(used.message, "submitted")

	# M7: per-document status as received.
	def test_a_per_document_status_is_stored_as_received(self):
		self.stage_all()
		payload = self.completion()
		statuses = {"aadhaar_front": "needs_review", "pan_card": "unreadable", "cancelled_cheque": "failed"}
		for document in payload["steps"][0]["documents"]:
			document["status"] = statuses.get(document["document_code"], document["status"])
		self.assertEqual(self.deliver(payload).status, 200)
		rows = {r.document_code: r.verification_status for r in self.request().requested_documents}
		for code, status in statuses.items():
			self.assertEqual(rows[code], status)
		self.assertEqual(rows["graduation_certificate"], "done")

	# (g)
	def test_a_repeated_delivery_gives_the_same_result(self):
		self.stage_all()
		payload = self.completion()
		self.deliver(payload)
		first = self.request()
		again = self.deliver(payload)
		self.assertEqual((again.status, again.message), (200, {"ok": True}))
		second = self.request()
		self.assertEqual(second.status, "Data Received")
		self.assertEqual(
			[(r.document_code, r.file) for r in first.requested_documents],
			[(r.document_code, r.file) for r in second.requested_documents],
		)
		self.assertEqual(
			[(e.document_code, e.key, e.value) for e in first.extractions],
			[(e.document_code, e.key, e.value) for e in second.extractions],
		)
		self.assertEqual(len(_files_of(self.request_name)), len(IMAGE_CODES))

	# (h)
	def test_a_delivery_for_another_ref_is_refused(self):
		payload = self.completion()
		payload["ref"] = "DCR-2026-9999.someotherlink"
		answer = self.deliver(payload)
		self.assertEqual((answer.status, answer.message), (404, GENERIC_ERROR))
		logs = frappe.get_all(
			"Error Log",
			filters={"method": ("like", "%store_verification%"), "error": ("like", "%category=stale_ref%")},
			fields=["error", "method", "metadata"],
		)
		self.assertTrue(logs)
		self.assertIn(self.request_name, logs[0].error)
		# The Error Log's copy of the form dict must not carry the payload (FR-032).
		for value in ("Asha", "ABCPV1234F", "999988887777", "XXXX XXXX 7777", "extracted"):
			self.assertNotIn(value, logs[0].metadata or "")
			self.assertNotIn(value, logs[0].error)
		self.assertEqual(self.request().status, "Link Sent")

	# I2: on a developer-mode site Frappe snapshots every exception into Error Log.
	def test_refusals_leave_no_payload_in_error_log_on_a_developer_mode_site(self):
		self.stage_all()
		before = set(frappe.get_all("Error Log", pluck="name"))
		stale = self.completion()
		stale["ref"] = "DCR-2026-9999.someotherlink"
		bad_schema = self.completion()
		del bad_schema["steps"][0]["provider"]
		with mock.patch.dict(frappe.local.conf, {"developer_mode": 1}):
			answers = [
				self.deliver(stale),
				self.deliver(bad_schema),
				self.deliver(self.completion(), secret="ef" * 32),
			]
			self.assertIsNone(self.last_exception.__context__)
			self.assertEqual(self.form_dict_at_error, {"cmd": None})
			# Frappe's own errors are logged and answered generically too.
			with mock.patch.object(service, "accept_delivery", side_effect=frappe.TimestampMismatchError):
				answers.append(self.deliver(self.completion()))

		self.assertEqual([a.status for a in answers], [404, 400, 401, 404])
		self.assertEqual({a.message for a in answers}, {GENERIC_ERROR})
		logs = frappe.get_all(
			"Error Log",
			filters={"name": ("not in", list(before) or [""])},
			fields=["method", "error", "metadata"],
		)
		# Only our own entries, one per logged refusal.
		self.assertEqual(len(logs), 4, [log.method for log in logs])
		self.assertTrue(all(log.method.startswith("Document collection portal") for log in logs))
		unexpected = next(log for log in logs if "category=unexpected" in log.error)
		self.assertIn("exception=TimestampMismatchError at ", unexpected.error)
		for log in logs:
			text = f"{log.method}\n{log.error}\n{log.metadata}"
			for value in ("Asha", "ABCPV1234F", "999988887777", "XXXX XXXX 7777", "extracted", "payload"):
				self.assertNotIn(value, text)

	# (i)
	def test_a_schema_invalid_body_gets_400(self):
		payload = self.completion()
		del payload["steps"][0]["provider"]
		answer = self.deliver(payload)
		self.assertEqual((answer.status, answer.message), (400, GENERIC_ERROR))
		logs = frappe.get_all("Error Log", filters={"error": ("like", "%category=schema%")}, fields=["error"])
		self.assertTrue(any("pointer=/steps/0/provider" in log.error for log in logs))
		self.assertEqual(self.request().status, "Link Sent")

	# (j)
	def test_a_resend_and_second_delivery_replace_the_first(self):
		self.stage_all()
		self.deliver(self.completion())
		first_files = {f.file_url for f in _files_of(self.request_name)}

		self.code = self.send(self.onboarding.name)
		# Until the next delivery, the first one stays.
		self.assertEqual(self.request().status, "Data Received")
		self.assertTrue(any(e.document_code == "pan_card" for e in self.request().extractions))

		self.upload("aadhaar_front", png_bytes(99), vdid="doc-new")
		answer = self.deliver(self.completion(codes=["aadhaar_front"]))
		self.assertEqual(answer.status, 200, answer)

		request = self.request()
		with_files = [r.document_code for r in request.requested_documents if r.file]
		self.assertEqual(with_files, ["aadhaar_front"])
		self.assertEqual(request.requested_documents[0].verification_document_id, "doc-new")
		self.assertEqual({e.document_code for e in request.extractions}, {"aadhaar_front"})
		files = _files_of(self.request_name)
		self.assertEqual(len(files), 1)
		self.assertNotIn(files[0].file_url, first_files)

	# (k)
	def test_a_flattening_failure_keeps_the_stored_bundle(self):
		self.stage_all()
		with mock.patch.object(service, "extraction_rows", side_effect=RuntimeError("boom")):
			answer = self.deliver(self.completion())
		self.assertEqual(answer.status, 200, answer)
		request = self.request()
		self.assertEqual(request.status, "Data Received")
		self.assertIn("XXXX XXXX 7777", request.verification_response)
		self.assertTrue(request.extraction_error)
		self.assertEqual(len(request.extractions), 0)
		(log,) = frappe.get_all(
			"Error Log",
			filters={"method": ("like", "%extraction failed%")},
			fields=["error"],
			order_by="creation desc",
			limit=1,
		)
		self.assertIn(f"request={self.request_name}", log.error)
		self.assertIn("exception=RuntimeError at ", log.error)

	# Ruling 2: a resend deletes the staged Files it clears.
	def test_resend_deletes_staged_files(self):
		self.upload("aadhaar_front", png_bytes(5), vdid="doc-1")
		self.assertEqual(len(_files_of(self.request_name)), 1)
		self.code = self.send(self.onboarding.name)
		self.assertEqual(_files_of(self.request_name), [])

	def test_resend_after_delivery_keeps_the_delivered_files(self):
		self.stage_all()
		self.deliver(self.completion())
		self.code = self.send(self.onboarding.name)
		rows = [r for r in self.request().requested_documents if r.file]
		self.assertEqual(len(rows), len(IMAGE_CODES))
		self.assertEqual(len(_files_of(self.request_name)), len(IMAGE_CODES))

	def test_the_old_code_stops_working_after_a_resend(self):
		old_code = self.code
		self.code = self.send(self.onboarding.name)
		self.assertEqual(self.get_request(code=old_code).status, 404)
		self.assertEqual(self.get_request().status, 200)

"""Unit tests for the callback signature check.

Deliberately free of frappe imports, like the module they cover, so they run
without a site or a database:

	cd apps/ninthsense && ../../env/bin/python -m unittest \
		ninthsense.core.tests.test_callback_signature -v
"""

import hashlib
import hmac
import json
import unittest

from ninthsense.core.callback_signature import (
	MAX_SKEW_SECONDS,
	verify_callback_signature,
)

SECRET = "0f8f7d2f85b02e8375b0ba92f6130bb9390c03021d7f9ad067c1bd551c3c3a3a"
OTHER_SECRET = "a" * 64
NOW = 1_789_000_000

BODY = json.dumps({"token": "tok-9", "payload": {"ref": "ONB-2026-0042"}}).encode()


def header_for(body: bytes, secret: str = SECRET, timestamp: int = NOW) -> str:
	digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
	return f"t={timestamp},v1={digest}"


class VerifyCallbackSignature(unittest.TestCase):
	def test_accepts_a_valid_signature(self):
		self.assertIsNone(verify_callback_signature(BODY, header_for(BODY), [SECRET], NOW))

	def test_rejects_a_body_with_one_byte_changed(self):
		tampered = BODY.replace(b"ONB-2026-0042", b"ONB-2026-0043")
		self.assertEqual(verify_callback_signature(tampered, header_for(BODY), [SECRET], NOW), "bad_digest")

	def test_rejects_a_signature_made_with_another_secret(self):
		self.assertEqual(
			verify_callback_signature(BODY, header_for(BODY, OTHER_SECRET), [SECRET], NOW),
			"bad_digest",
		)

	def test_rejects_a_timestamp_ten_minutes_old(self):
		stale = header_for(BODY, timestamp=NOW - 600)
		self.assertEqual(verify_callback_signature(BODY, stale, [SECRET], NOW), "stale_timestamp")

	def test_rejects_a_timestamp_ten_minutes_ahead(self):
		ahead = header_for(BODY, timestamp=NOW + 600)
		self.assertEqual(verify_callback_signature(BODY, ahead, [SECRET], NOW), "stale_timestamp")

	def test_accepts_the_edge_of_the_window_and_rejects_one_second_past_it(self):
		for offset in (MAX_SKEW_SECONDS, -MAX_SKEW_SECONDS):
			edge = header_for(BODY, timestamp=NOW + offset)
			self.assertIsNone(verify_callback_signature(BODY, edge, [SECRET], NOW))
		for offset in (MAX_SKEW_SECONDS + 1, -MAX_SKEW_SECONDS - 1):
			past = header_for(BODY, timestamp=NOW + offset)
			self.assertEqual(verify_callback_signature(BODY, past, [SECRET], NOW), "stale_timestamp")

	def test_rejects_a_missing_header(self):
		for header in (None, "", "   "):
			self.assertEqual(verify_callback_signature(BODY, header, [SECRET], NOW), "missing_header")

	def test_rejects_a_malformed_header(self):
		digest = hmac.new(SECRET.encode(), b"x", hashlib.sha256).hexdigest()
		for header in (
			f"{NOW}.{digest}",
			f"v1={digest}",
			f"t={NOW}",
			f"t={NOW},v1={digest[:63]}",
			f"t={NOW},v1={digest.upper()}",
			f"t={NOW},v1={digest},extra=1",
			f"t=,v1={digest}",
			f"t=abc,v1={digest}",
			f" t={NOW},v1={digest}",
		):
			self.assertEqual(
				verify_callback_signature(BODY, header, [SECRET], NOW),
				"malformed_header",
				msg=header,
			)

	def test_rejects_an_empty_body(self):
		self.assertEqual(verify_callback_signature(b"", header_for(b""), [SECRET], NOW), "missing_body")

	def test_rejects_when_no_secret_is_configured(self):
		for secrets in ([], [""], ["  ", None]):
			self.assertEqual(verify_callback_signature(BODY, header_for(BODY), secrets, NOW), "no_secret")

	def test_accepts_any_of_the_candidate_secrets_so_rotation_needs_no_code_change(self):
		self.assertIsNone(
			verify_callback_signature(BODY, header_for(BODY, OTHER_SECRET), [SECRET, OTHER_SECRET], NOW)
		)


if __name__ == "__main__":
	unittest.main()

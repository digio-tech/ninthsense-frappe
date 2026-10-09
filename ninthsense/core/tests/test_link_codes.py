import hashlib
import inspect
import re
import secrets
import unittest
from unittest import mock

from ninthsense.core import link_codes
from ninthsense.core.link_codes import codes_match, hash_code, mint_link


def fixed_factory(nbytes):
	return f"tok{nbytes}"


class MintLink(unittest.TestCase):
	def test_shape_with_a_deterministic_factory(self):
		link = mint_link("DCR-2026-0001", fixed_factory)
		self.assertEqual(link.code, "tok32")
		self.assertEqual(link.code_hash, hashlib.sha256(b"tok32").hexdigest())
		self.assertEqual(link.ref, "DCR-2026-0001.tok12")

	def test_real_factory_ref_shape_and_length(self):
		link = mint_link("DCR-2026-0001")
		self.assertRegex(link.ref, r"^DCR-2026-0001\.[A-Za-z0-9_-]{16}$")
		self.assertLess(len(link.ref), 128)
		self.assertLess(len(link.code), 128)
		self.assertEqual(link.code_hash, hash_code(link.code))

	def test_real_factory_uses_32_and_12_bytes(self):
		calls = []

		def spy(n):
			calls.append(n)
			return "x"

		mint_link("DCR-2026-0001", spy)
		self.assertEqual(calls, [32, 12])

	def test_default_factory_is_secrets_token_urlsafe(self):
		default = inspect.signature(mint_link).parameters["token_factory"].default
		self.assertIs(default, secrets.token_urlsafe)

	def test_two_mints_never_share_a_code_or_ref(self):
		links = [mint_link("DCR-2026-0001") for _ in range(200)]
		self.assertEqual(len({link.code for link in links}), 200)
		self.assertEqual(len({link.ref for link in links}), 200)
		self.assertEqual(len({link.code_hash for link in links}), 200)


class HashCode(unittest.TestCase):
	def test_is_sha256_hex(self):
		self.assertEqual(hash_code("abc"), hashlib.sha256(b"abc").hexdigest())
		self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", hash_code("abc")))


class CodesMatch(unittest.TestCase):
	def test_matching_code(self):
		self.assertTrue(codes_match(hash_code("secret-code"), "secret-code"))

	def test_wrong_code(self):
		self.assertFalse(codes_match(hash_code("secret-code"), "other-code"))

	def test_none_and_empty(self):
		stored = hash_code("secret-code")
		self.assertFalse(codes_match(stored, None))
		self.assertFalse(codes_match(stored, ""))
		self.assertFalse(codes_match(None, "secret-code"))
		self.assertFalse(codes_match("", "secret-code"))

	def test_over_128_characters(self):
		long_code = "a" * 129
		self.assertFalse(codes_match(hash_code(long_code), long_code))
		exact = "a" * 128
		self.assertTrue(codes_match(hash_code(exact), exact))

	def test_non_string_code(self):
		self.assertFalse(codes_match(hash_code("1"), 1))

	def test_uses_constant_time_compare(self):
		with mock.patch.object(link_codes.hmac, "compare_digest", return_value=True) as compare:
			self.assertTrue(codes_match(hash_code("x"), "x"))
		compare.assert_called_once()


if __name__ == "__main__":
	unittest.main()

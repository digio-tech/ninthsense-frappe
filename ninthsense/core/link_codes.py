"""Link codes and link refs (R8). Frappe-free.

The code is the candidate's only identity, so only its SHA-256 is stored: a database read
cannot reissue a live link. The ref is fresh for every link, so 9thSense never sees the same
case reference twice -- not across sites (the request name restarts at DCR-...-0001 on each)
and not across two links of one request.
"""

import hashlib
import hmac
import secrets
from collections.abc import Callable
from typing import NamedTuple

from ninthsense.core.config import MAX_TOKEN_LENGTH

CODE_BYTES = 32
REF_BYTES = 12


class Link(NamedTuple):
	code: str
	code_hash: str
	ref: str


def hash_code(code: str) -> str:
	return hashlib.sha256(code.encode("utf-8")).hexdigest()


def mint_link(request_name: str, token_factory: Callable[[int], str] = secrets.token_urlsafe) -> Link:
	"""A new code, its hash and a `<request>.<random>` ref for one link issue."""
	code = token_factory(CODE_BYTES)
	ref = f"{request_name}.{token_factory(REF_BYTES)}"
	if len(ref) >= MAX_TOKEN_LENGTH:
		raise ValueError("link ref too long")
	return Link(code=code, code_hash=hash_code(code), ref=ref)


def codes_match(stored_hash: str | None, code: str | None) -> bool:
	"""Constant-time comparison of a presented code against the stored hash."""
	if not stored_hash or not isinstance(stored_hash, str):
		return False
	if not code or not isinstance(code, str) or len(code) > MAX_TOKEN_LENGTH:
		return False
	return hmac.compare_digest(hash_code(code), stored_hash)

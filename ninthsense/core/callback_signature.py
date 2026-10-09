"""HMAC verification for the candidate portal's completion callback.

The callback used to be authenticated by the link token alone, and the token is
in the candidate's address bar: the party being verified could post their own
extraction values and have them written to their own employee record. The
portal now signs the exact bytes it puts on the wire with a shared secret, and
this module is the only thing that decides whether a delivery is genuine.

Deliberately free of frappe imports, so it is a pure function that can be
tested without a site or a database. The caller supplies the secrets and the
clock.

Wire format, set by the portal:

	X-Portal-Signature: t=<unix_seconds>,v1=<hex_sha256>

The timestamp is signed alongside the body, so a captured delivery cannot be
replayed once the window has passed.
"""

import hashlib
import hmac
import re
from collections.abc import Sequence

SIGNATURE_HEADER = "X-Portal-Signature"

#: How far apart the two clocks may be, in either direction.
MAX_SKEW_SECONDS = 300

#: Anchored and exact: lower-case hex only, no extra fields, no leading space.
#: A header the portal did not produce is a rejection, not something to salvage.
_HEADER = re.compile(r"\At=(\d{1,20}),v1=([0-9a-f]{64})\Z")


def verify_callback_signature(
	raw_body: bytes,
	header: str | None,
	secrets: Sequence[str | None],
	now: int,
) -> str | None:
	"""Returns None when the delivery is genuine, else a short failure category.

	The category is for the log; the caller answers with one generic 401 either
	way, so a caller learns nothing about which check it failed.

	`secrets` is a list, though today only one is configured: a rotation window
	means accepting the old and the new secret at once, and taking a list here
	means that window is a second settings field rather than a change to the
	verification path.
	"""
	if not raw_body:
		return "missing_body"

	if not header or not header.strip():
		return "missing_header"

	match = _HEADER.match(header)
	if not match:
		return "malformed_header"

	timestamp, digest = match.group(1), match.group(2)

	if abs(now - int(timestamp)) > MAX_SKEW_SECONDS:
		return "stale_timestamp"

	usable = [s for s in secrets if s and s.strip()]
	if not usable:
		return "no_secret"

	# The timestamp is signed with the body, so the bytes are built rather than
	# decoded: an encoding round-trip is one more way for the two sides to differ.
	signed_content = f"{timestamp}.".encode() + raw_body

	for secret in usable:
		expected = hmac.new(secret.encode(), signed_content, hashlib.sha256).hexdigest()
		if hmac.compare_digest(expected, digest):
			return None

	return "bad_digest"

import unittest
from datetime import datetime, timedelta

from ninthsense.core.link_state import link_state

NOW = datetime(2026, 10, 7, 12, 0, 0)
FUTURE = NOW + timedelta(days=3)
PAST = NOW - timedelta(seconds=1)


class LinkState(unittest.TestCase):
	def test_open(self):
		self.assertEqual(link_state("Link Sent", None, FUTURE, NOW), "open")
		self.assertEqual(link_state("Data Received", None, FUTURE, NOW), "open")

	def test_cancelled_is_revoked(self):
		self.assertEqual(link_state("Cancelled", None, FUTURE, NOW), "revoked")

	def test_completed_or_delivered_is_submitted(self):
		self.assertEqual(link_state("Completed", None, FUTURE, NOW), "submitted")
		self.assertEqual(link_state("Data Received", NOW, FUTURE, NOW), "submitted")

	def test_past_expiry_is_expired(self):
		self.assertEqual(link_state("Link Sent", None, PAST, NOW), "expired")

	def test_precedence(self):
		# Cancelled beats delivered beats expired.
		self.assertEqual(link_state("Cancelled", NOW, PAST, NOW), "revoked")
		self.assertEqual(link_state("Data Received", NOW, PAST, NOW), "submitted")
		self.assertEqual(link_state("Completed", None, PAST, NOW), "submitted")


if __name__ == "__main__":
	unittest.main()

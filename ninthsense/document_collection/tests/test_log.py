"""log_event reaches the app's logger at INFO, with only allow-listed fields."""

import logging

import frappe

from ninthsense.document_collection.log import log_event
from ninthsense.document_collection.tests.error_logs import AppTestCase


class _Capture(logging.Handler):
	def __init__(self):
		super().__init__(level=logging.NOTSET)
		self.records = []

	def emit(self, record):
		self.records.append(record)


class TestLog(AppTestCase):
	def test_event_is_written_at_info(self):
		logger = frappe.logger("ninthsense")
		# What frappe.logger() starts at outside a dev server.
		logger.setLevel(logging.ERROR)
		capture = _Capture()
		logger.addHandler(capture)
		try:
			log_event("portal_call", request="DCR-2026-0001", outcome="ok", candidate_name="Asha")
		finally:
			logger.removeHandler(capture)

		self.assertEqual(len(capture.records), 1)
		record = capture.records[0]
		self.assertEqual(record.levelno, logging.INFO)
		self.assertEqual(record.msg, {"event": "portal_call", "request": "DCR-2026-0001", "outcome": "ok"})

import unittest

from ninthsense.core.file_types import MB, check_upload

ALLOWED = "pdf,jpeg,jpg,png"


class CheckUpload(unittest.TestCase):
	def test_empty_is_no_file(self):
		self.assertEqual(check_upload(b"", "pdf", ALLOWED, 3), "no_file")
		self.assertEqual(check_upload(None, "pdf", ALLOWED, 3), "no_file")

	def test_over_the_limit_is_file_size(self):
		self.assertEqual(check_upload(b"x" * (MB + 1), "pdf", ALLOWED, 1), "file_size")
		self.assertIsNone(check_upload(b"x" * MB, "pdf", ALLOWED, 1))

	def test_undetected_or_not_allowed_is_file_type(self):
		# filetype.guess gives None for HTML, whatever the file is called.
		self.assertEqual(check_upload(b"<html>", None, ALLOWED, 3), "file_type")
		self.assertEqual(check_upload(b"GIF89a", "gif", ALLOWED, 3), "file_type")
		self.assertEqual(check_upload(b"%PDF", "pdf", "png", 3), "file_type")

	def test_jpg_and_jpeg_are_one_type(self):
		self.assertIsNone(check_upload(b"\xff\xd8", "jpg", "jpeg", 3))
		self.assertIsNone(check_upload(b"\xff\xd8", "jpeg", "jpg", 3))

	def test_dotted_and_cased_allowed_list(self):
		self.assertIsNone(check_upload(b"%PDF", "pdf", ".PDF, .png", 3))

	def test_allowed_match(self):
		self.assertIsNone(check_upload(b"\x89PNG", "png", ALLOWED, 3))


if __name__ == "__main__":
	unittest.main()

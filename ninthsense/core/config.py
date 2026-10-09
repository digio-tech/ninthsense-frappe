"""Constants only. No frappe imports (T020)."""

LINK_VALIDITY_DAYS = 14
SCHEMA_VERSION = "2.0"
SUPPORTED_SCHEMA_VERSIONS = ("2.0",)
CATALOGUE_VERSION = 1

GOAL_KEY = "onboarding"
STAGE_LABEL = "Onboarding"

CALLBACK_PATH = "/api/method/ninthsense.document_collection.portal_api.store_verification"

MAX_TOKEN_LENGTH = 128
ALLOWED_EXTENSIONS = (".pdf", ".jpg", ".jpeg", ".png")
MAX_FILE_SIZE_MB = 10

GENERIC_ERROR = "This link is not valid."
HR_ROLES = ("HR User", "HR Manager")

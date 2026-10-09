# Test fixtures

## completion-mock.json

A completion body as the unchanged portal posts it to `store_verification`, for the contract
test and the portal integration tests.

**Built, not recorded.** It was assembled by hand from the portal's source at hrms-wrapper
develop 361560f, because recording from a running portal was not quick:

- the envelope (`schema_version`, `ref`, `goal_key`, `stage`, `catalogue_version`, `status`,
  `completed_at`, one step with `provider`, `result`, `documents`, `extractions`,
  `missing_documents`, and the echoed `x-hrms`) follows `buildCompletionPayload` and
  `describeDocument` in `lib/completion.ts`
- `provider`, `result` (`cross_match` plus one check per document), the merged `extractions`
  and each document's `doc_index`, `confidence`, `status: "done"` follow the mock provider in
  `lib/provider/mock.ts`
- the `extracted` blocks are NOT the mock's own fixtures (`mocks/fixtures/*.json` covers six
  codes and uses other key names). They carry the 9thSense keys the fill reads, from the old
  app's `field_catalogue.py`, for every document in the seeded list: aadhaar_front, pan_card,
  resume, graduation_certificate, cancelled_cheque, latest_pay_slip, bank_statement, passport

All values are samples: a fictitious candidate, Digio India as employer, `@example.com`
addresses, and the dummy Aadhaar `999988887777` so masking is exercised. `ref` and the
`verification_document_id`s are placeholders that the integration tests replace with the
request's own. `test_contract.py` asserts the file validates against the vendored completion
schema.

The Aadhaar front's `name` (and the merged `extractions.name`) is `Asha Rani Verma`, a
three-part name, so the fill tests can check that first, middle and last name are split
(batch 4).

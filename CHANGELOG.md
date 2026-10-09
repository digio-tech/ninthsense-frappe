# Changelog

## 1.0.0

First release, for Frappe, ERPNext and HRMS v16 and develop.

- **Send onboarding link** on Employee Onboarding: emails the candidate a 14-day link to the 9thSense
  portal, from the Email Template "Document Request Link". Sending again issues a fresh link and
  closes the old one. When the email cannot go out, HR is shown the link to pass on.
- **Document Collection Request**: one per onboarding, with the documents the candidate uploaded,
  the values 9thSense read, 9thSense's overall result and the latest fill report.
- **Create › Employee** fills every still-empty Employee field it can from the candidate's documents,
  and attaches the documents to the Employee. HR reviews the form and saves it as usual.
- **Document Collection Templates**: named sets of documents, each with its own field mapping, edited
  with one dropdown per Employee field. HR picks a template when sending, with the default
  preselected. The previous employer's offer letter and pay slip never fill the new job's terms.
- **Standard Onboarding**, a ready-to-use default template with 8 documents and its mapping, and 14
  Employee Document Types, created on install only when missing.
- **Aadhaar Number (last 4 digits)** on Employee. Aadhaar numbers are masked everywhere the app
  stores them.
- **Document Collection Settings** for the portal address, the callback secret, and the support email
  and accent colour shown to the candidate.
- Works with the existing 9thSense portal unchanged: it answers the portal at the addresses it already calls
  (`ninthsense.document_collection.portal_api.*`), in request format 2.0.
- Desk navigation under Frappe HR: a Document Collection workspace, sidebar and desktop icon.

<div align="center">
	<img src="ninthsense/public/images/9thsense-logo.png" height="96" alt="9thSense">
	<h2>9thSense Onboarding</h2>
	<p>Collect a new hire's documents with 9thSense and pre-fill the Employee from them, inside Frappe HR.</p>
</div>

## Key Features

- **Send onboarding link.** From an Employee Onboarding, email the candidate a 14-day link to the 9thSense portal. Sending again issues a fresh link and closes the old one. If the email cannot go out, HR is shown the link to pass on.
- **Document Collection Request.** One per onboarding, showing the documents the candidate uploaded, what 9thSense read from them, and 9thSense's overall result.
- **Pre-filled Employee.** **Create › Employee** fills every still-empty Employee field it can from the candidate's documents: names, date of birth, PAN, address, bank details, education and work history. It attaches the documents to the Employee. HR reviews the form and saves it as usual, and a fill report lists what was filled and what was skipped.
- **Templates and a mapping editor.** Named document sets, each with its own field mapping, edited with one dropdown per Employee field. HR picks a template when sending.
- **Privacy by default.** Aadhaar numbers are reduced to their last four digits before anything is stored. Logs carry only record IDs and statuses.

The app never calls 9thSense directly. The 9thSense portal calls the app.

## Requirements

- Frappe, ERPNext and HRMS **v16**, or develop (v17)
- Python 3.14
- A 9thSense portal tenant configured for this site (see [Configuration](#configuration))

## Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app https://github.com/digio-tech/ninthsense-frappe --branch version-16
bench --site $SITE_NAME install-app ninthsense
```

ERPNext and HRMS must be installed first. The app can be installed before or after the setup wizard. Install creates only the app's own records, and only when they are missing, so later installs and migrates never overwrite HR's edits:

- 14 **Employee Document Types** (Aadhaar, PAN, passport, education, employment and bank documents)
- the Email Template **Document Request Link**, the invitation the candidate receives
- the **Standard Onboarding** template: 8 documents and their field mapping, enabled and the default
- the Employee field **Aadhaar Number (last 4 digits)**, plus HRMS's own India fields on Employee (PAN, IFSC, MICR, PF account)

It creates no company data: no departments, designations, letterheads or demo records.

## Configuration

1. Open **Document Collection Settings**:

	| Setting | Description |
	| --- | --- |
	| Portal URL | The 9thSense portal address, e.g. `https://portal.example.com`, with no path. `https` is required except on `localhost`. |
	| Callback Secret | The secret the portal signs its callback with: at least 32 characters, the same value as the portal tenant's callback secret. |
	| Support Email | Optional. Shown to candidates as the address to write to for help. |
	| Portal Accent Colour | Optional. The accent colour the portal shows the candidate. |

2. Add an outgoing **Email Account** marked as the default outgoing account. Without one, links are still issued and HR is shown them to pass on, but no email goes out.
3. Review **Standard Onboarding**, or create your own templates.

On the portal side, the tenant for this site needs four things:
- its HR system base URL set to this site's URL
- the same callback secret
- an `onboarding` entry in its goals map
- request format 2.0

A mismatched secret shows as `CALLBACK SIGNATURE REJECTED (bad_digest)` in the Error Log.

Only **HR User** and **HR Manager** can send links, see requests and edit templates. Settings are for HR Manager and System Manager.

## Usage

1. Create the Job Applicant, Job Offer and Employee Onboarding as usual.
2. On the Employee Onboarding, press **Send onboarding link**. When more than one template is enabled, pick one; the default is preselected.
3. The candidate uploads their documents on the portal. The request then shows **Data Received**.
4. Submit the onboarding and press **Create › Employee**. The form opens unsaved with the candidate's details filled in. A notice links to the fill report.
5. Review and save. The request becomes **Completed**, and the documents are attached to the Employee.

**Templates.** Each **Document Collection Template** lists its documents (whether each is mandatory, the accepted file types and the size limit) and maps which document fills each Employee field, with an optional fallback document. Exactly one enabled template is the default.
- A field can only be read from a document in the same template that can carry it.
- The previous employer's offer letter and pay slip never fill designation, department, CTC or joining date.
- Create › Employee always reads the template's current mapping.
- Document types live in **Employee Document Type**. A type's code is how the portal addresses it, so add a new type rather than renaming a code.

**Notes.**
- **Portal endpoints.** The portal calls the guest endpoints `ninthsense.document_collection.portal_api.*`. Each call is authenticated by the candidate's link code or by the callback signature.
- **`make_employee` override.** The app wraps HRMS's `make_employee` (Create › Employee). Another app that also overrides `make_employee` conflicts with it.
- **v16 navigation.** On v16 the app re-ships its Document Collection sidebar and desktop icon after every migrate, so desk edits to those two records don't survive a migrate.

## Uninstall

```bash
bench --site $SITE_NAME uninstall-app ninthsense
```

This removes the app's doctypes and their data, its workspace and, on v16, its sidebar and desktop icon. It leaves:
- the Aadhaar Number (last 4 digits) field on Employee
- HRMS's India fields
- the Email Template
- uploaded files, including the copies attached to Employees

Reinstalling works.

## Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/ninthsense
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier

Tests:

```bash
# integration tests, on a test site only (never one with real data)
bench --site $TEST_SITE set-config allow_tests true
bench --site $TEST_SITE run-tests --app ninthsense

# quality gate from the repository root: ruff, the Frappe-free unit tests and the Marketplace semgrep scan
git clone --depth 1 https://github.com/frappe/marketplace /tmp/marketplace
MARKETPLACE_RULES=/tmp/marketplace scripts/check
```

<details>
<summary>Setting up a test site non-interactively</summary>

```bash
bench new-site $TEST_SITE --install-app erpnext --install-app hrms
bench --site $TEST_SITE execute frappe.desk.page.setup_wizard.setup_wizard.setup_complete \
  --kwargs '{"args": {"language":"English","country":"India","timezone":"Asia/Kolkata","currency":"INR","full_name":"Test Admin","email":"admin@example.com","password":"admin","company_name":"Test Pvt Ltd","company_abbr":"TPL","chart_of_accounts":"Standard","fy_start_date":"2026-04-01","fy_end_date":"2027-03-31"}}'
bench --site $TEST_SITE install-app ninthsense
```

`scripts/check` uses the bench's Python for the unit tests (set `BENCH_PY` to use another). It fails only on findings the Marketplace blocks on. The four portal endpoints show as guest-method advisories, which don't block. Without `MARKETPLACE_RULES`, the semgrep step is reported as incomplete.

</details>

## License

MIT. See [license.txt](license.txt).

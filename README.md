# 9thSense Onboarding

A Frappe HR app that collects a new hire's onboarding documents through the 9thSense portal and fills
the Employee from them.

- On an **Employee Onboarding**, HR presses **Send onboarding link**. The app creates one Document
  Collection Request for the onboarding and emails the candidate, at the Job Applicant's address, a
  link to the portal. The link is valid for 14 days. Sending again issues a fresh link and the old one
  stops working.
- The candidate uploads the documents on the portal. 9thSense checks them, and the portal posts the
  files and what 9thSense read back to this site. The request then shows the documents, the values
  read and 9thSense's overall result.
- When HR chooses **Create › Employee**, the form opens with the candidate's details filled in from
  those documents. Only empty fields are filled. A fill report on the request lists what was filled and
  what was skipped, and why. HR reviews the form and saves it as usual.

The app never talks to 9thSense itself. It adds one field to Employee, **Aadhaar Number (last 4
digits)**, which only ever holds the last four digits.

## Supported versions

Frappe, ERPNext and HRMS v16 and develop (v17), on Python 3.14. v15 is not supported.
ERPNext and HRMS must be installed first (`required_apps`).

## First install

```bash
bench get-app https://github.com/digio-tech/ninthsense-frappe --branch version-16
bench --site <site> install-app ninthsense
```

The app can be installed before or after the setup wizard. Install creates only the app's own records:

- the 14 **Employee Document Types** (Aadhaar, PAN, passport, education, employment and bank documents)
- the Email Template **Document Request Link**, the invitation the candidate receives
- one **Document Collection Template**, "Standard Onboarding": enabled, the default, with 8 documents
  and its field mapping. It is created only when no template exists.
- the Employee field **Aadhaar Number (last 4 digits)**, and HRMS's own India fields on Employee (PAN,
  IFSC, MICR, PF account and the rest), which HRMS otherwise adds only when the setup wizard creates an
  Indian company

It creates no company data: no departments, designations, jobs, letterheads or demo records. Each seeded
record is created only when it is missing, so a later install or migrate never overwrites HR's edits.

After install:

1. Open **Document Collection Settings** and fill in the values below. The app refuses to send a link
   until they are valid.
2. Make sure the site has an outgoing Email Account marked as the default outgoing account. Without
   one, the link is still issued and HR is shown it to pass on, but no email goes out.
3. Review "Standard Onboarding", or create your own templates.

Only HR User and HR Manager can send links, see requests and edit templates. Settings are for HR
Manager and System Manager.

## Settings

| Setting | What it is |
| --- | --- |
| Portal URL | The portal address you are given, e.g. `https://portal.example.com`, with no path. `https` is required unless the host is `localhost`. |
| Callback Secret | The shared secret the portal signs its callback with. At least 32 characters. |
| Support Email | Optional. Shown to candidates as the address to write to for help. |
| Portal Accent Colour | Optional. The accent colour the portal shows the candidate. |

## Values that must match the portal

| This app | The portal | Note |
| --- | --- | --- |
| Settings, Callback Secret | The tenant's completion-callback secret | Byte for byte. A mismatch shows as `CALLBACK SIGNATURE REJECTED (bad_digest)` in Error Log. |
| Settings, Portal URL | The tenant's host | The candidate's link is `{portal_url}/s/{code}`. |
| This site's URL | The tenant's `hrms` base URL | The portal calls this app's endpoints at this origin. |
| `goal_key` = `onboarding` (fixed) | An entry `onboarding` in the tenant's goals map | Otherwise the portal refuses the collection. |
| `catalogue_version` = 1 | Logged by the portal only | |
| Request format version 2.0 | The portal's request and completion schemas | The schemas are vendored in `ninthsense/core/contract/` and pinned by digest. |

## Templates and the mapping editor

The documents to ask for live in **Document Collection Template**. Each template lists its documents
(with whether each is mandatory, the file types accepted and the size limit) and maps which document
fills each Employee field: one dropdown per field, grouped by section, with an optional fallback
document.

- While any template is enabled, exactly one enabled template is the default. When more than one template is enabled, Send onboarding
  link asks HR to pick one, with the request's current template or the default preselected.
- Create › Employee reads the request's template mapping as it stands at that moment.
- A field can only be read from a document in the same template that can carry it. The previous
  employer's offer letter and pay slip never fill designation, department, CTC or joining date: the
  editor does not offer them, and saving such a row is refused.
- The document types themselves (name, code, category, defaults) are in **Employee Document Type**.
  A document code is what the portal addresses the document by: add a new type rather than renaming an
  existing code.

## Navigation

On v16 the app ships a Workspace Sidebar and a Desktop Icon, both named "Document Collection" and
filed under Frappe HR (`app` = `hrms`). v16's migrate deletes app-level rows that their `app` does not
ship, so the app puts both back after every migrate (an `after_migrate` hook). Edits made to these two
rows in the desk do not survive a migrate on v16. Develop uses the app's own Sidebar and Dock and is
not affected.

## Endpoints and overrides

- The portal calls this app at `ninthsense.document_collection.portal_api.*` (`get_request`,
  `store_document`, `discard_document`, `store_verification`). They are guest endpoints: each request
  is authenticated by the link code or by the callback signature.
- The app wraps HRMS's `make_employee` (Employee Onboarding's Create › Employee), so any other app that
  overrides `make_employee` conflicts with it: which one runs depends on the order the apps are installed in.

## Uninstall

```bash
bench --site <site> uninstall-app ninthsense
```

Uninstall drops the app's doctypes and their data (requests, templates, document types, Settings), the
workspace and, on v16, the Desktop Icon and Workspace Sidebar. It leaves:

- the Employee field **Aadhaar Number (last 4 digits)** (Custom Field `Employee-aadhaar_number`) and the
  values stored in it
- HRMS's India fields on Employee, which belong to HRMS
- the Email Template **Document Request Link**
- the files candidates uploaded (File records), including the copies attached to Employees

Installing again afterwards works and seeds the records above again.

## Development and tests

From the bench root, with the app's source tree linked in:

```bash
ln -s <path to this repository> apps/ninthsense
./env/bin/pip install -e apps/ninthsense
echo ninthsense >> sites/apps.txt   # check the file ended with a newline first

bench new-site <test site> --install-app erpnext --install-app hrms
bench --site <test site> install-app ninthsense
bench --site <test site> set-config allow_tests true
bench build --app ninthsense
```

To finish the setup wizard non-interactively with an Indian company:

```bash
bench --site <test site> execute frappe.desk.page.setup_wizard.setup_wizard.setup_complete \
  --kwargs '{"args": {"language":"English","country":"India","timezone":"Asia/Kolkata","currency":"INR","full_name":"Test Admin","email":"admin@example.com","password":"admin","company_name":"Test Pvt Ltd","company_abbr":"TPL","domains":["Services"],"chart_of_accounts":"Standard","fy_start_date":"2026-04-01","fy_end_date":"2027-03-31","bank_account":"HDFC"}}'
```

Tests:

- Integration tests, on a test site: `bench --site <test site> run-tests --app ninthsense`.
  Never run them on a site with real data.
- The quality gate, from the repository root: `scripts/check`. It runs ruff, the Frappe-free unit
  tests (`python -m unittest discover -s ninthsense/core -t .`, with the bench's Python;
  set `BENCH_PY` to use another) and the Frappe Marketplace's semgrep scan.
- For the semgrep step, clone the marketplace and point `MARKETPLACE_RULES` at the clone (or at its
  `validation/semgrep-rules` folder). It uses `semgrep`, or `uvx semgrep` when semgrep is not on PATH,
  and fails only on findings the marketplace blocks on (`is_blocking`, or severity ERROR, CRITICAL or
  HIGH). The four portal endpoints show as guest-method advisories, which do not block.

  ```bash
  git clone --depth 1 https://github.com/frappe/marketplace /tmp/marketplace
  MARKETPLACE_RULES=/tmp/marketplace scripts/check
  ```

  Without `MARKETPLACE_RULES` the step is skipped and reported as incomplete (and fails when `CI` is set).

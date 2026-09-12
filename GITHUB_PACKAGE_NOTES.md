# GitHub source package

This package was prepared from American_Express_Employee_Portal_Org_Management.zip.
The original ZIP is unchanged. No files have been uploaded to GitHub.

## Privacy-related exclusions

- The complete data/ directory, including the existing workspace database,
  account records, session records, attendance records, and runtime markers.
- Existing screenshots, which can contain account or document information.
- tests/last_run.txt and qa/interface_results.json, which are previous local
  test outputs rather than application source.

The application code, frontend assets, startup scripts, dependency files,
test source, and branding notice are preserved. The .gitignore is extended
to help prevent future accidental commits of runtime data and secrets.
README.md and QUICK_START.md clarify the source-only distribution.

## Running this copy

Follow QUICK_START.md. On a new installation, create the administrator
through first-time setup. Existing accounts, documents, and attendance do
not transfer through this source package. Keep your original data folder
backed up privately; do not commit it to Git.

## Repository and deployment

Use a private repository unless public sharing is explicitly intended.
This package does not grant permission to use or publish third-party branding.
Retain BRANDING_NOTICE.txt and do not represent this as an official service.
Uploading source to a repository is not a deployment of the backend.

A limited scan found no common token/private-key patterns in the retained
text files and no exact matches to the database email or credential strings
checked. This is not a comprehensive security audit. The application was
not executed or retested while preparing this package.

"""
Records: the end-to-end record of everything that happens in ScrapTrust.

- ``store.RecordsStore``: SQLite (WAL) database ``data/records/records.db`` with
  * ``activity``      every event (sign-in, message, upload, assessment, report, library action, admin view...),
                      structured JSON detail, indexed by day/month/year, full-text searchable (FTS5)
  * ``library``       each user's own items (uploads, generated reports, assessments): rename, pin, open, download
  * ``observations``  every black-mass reading in structured form (gun values, model results); UNLABELLED until
                      an admin attaches a lab (ICP-OES) result, which makes it CONFIRMED training data
  * ``learning_runs`` self-learning runs (candidate retrain, held-out comparison, promoted or not)
- ``pdf.write_text_pdf``: dependency-free PDF writer for library downloads.

Users only ever see their own library rows. The activity log, observations and learning runs are admin-only.
"""

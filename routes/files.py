"""Downloading submitted project work.

One place, one rule: whoever is on the placement's chain can read its files.
The student who sent it, the supervising lecturer, that lecturer's university,
the company that owns the brief, and administrators. Nobody else, whatever
role they hold.

Files are streamed from disk by their database record, never by a path that
came from the browser.
"""
from flask import Blueprint, abort, g, send_file

import storage
from auth_utils import login_required
from db import query
from workflow import (can_access_submission, record_download, submission_files,
                      submission_for)

files_bp = Blueprint("files", __name__, url_prefix="/files")


def _guard(submission_id):
    sub = submission_for(submission_id)
    if not sub:
        abort(404)
    if not can_access_submission(sub):
        abort(403)
    return sub


@files_bp.route("/<int:file_id>")
@login_required
def download(file_id):
    """One file, under the name the student gave it."""
    row = query("SELECT * FROM submission_files WHERE id=%s", (file_id,), one=True)
    if not row:
        abort(404)

    _guard(row["submission_id"])

    try:
        path = storage.absolute_path(row["relative_path"])
    except storage.UploadError:
        abort(410)

    record_download(g.user["id"], row["submission_id"], file_id, "file")
    return send_file(path, as_attachment=True,
                     download_name=row["original_name"],
                     mimetype=row["mime_type"] or "application/octet-stream")


@files_bp.route("/submission/<int:submission_id>/archive")
@login_required
def archive(submission_id):
    """Every file in one submitted version, zipped for download."""
    sub = _guard(submission_id)
    rows = submission_files(submission_id)
    if not rows:
        abort(404)

    folder = f"{sub['title']}-v{sub['version']}"

    # One missing file should not cost the reviewer the other nine.
    present = []
    for row in rows:
        try:
            storage.absolute_path(row["relative_path"])
            present.append(row)
        except storage.UploadError:
            continue
    if not present:
        abort(410)

    bundle = storage.build_archive(present, folder)

    record_download(g.user["id"], submission_id, None, "archive")
    return send_file(bundle, mimetype="application/zip", as_attachment=True,
                     download_name=f"{storage.secure_filename(folder) or 'project'}.zip")

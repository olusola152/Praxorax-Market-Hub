"""Where submitted project files actually live.

Files are written under UPLOAD_FOLDER, one directory per assignment and
submission version:

    uploads/submissions/<assignment_id>/v<version>/<stored_name>

The database row in submission_files is the record; this module is the disk.
Nothing here trusts a filename that came from a browser — the stored name is
generated, and every path is checked to be inside UPLOAD_FOLDER before it is
opened.
"""
import hashlib
import io
import mimetypes
import os
import re
import secrets
import zipfile

from flask import current_app
from werkzeug.utils import secure_filename

SUBMISSIONS_DIR = "submissions"

# Anything a student might hand over as project work. Executables and scripts
# that browsers or mail clients run on sight are deliberately absent.
ALLOWED_EXTENSIONS = {
    "zip", "rar", "7z", "tar", "gz", "tgz",
    "pdf", "doc", "docx", "odt", "rtf", "txt", "md", "csv", "xls", "xlsx",
    "ppt", "pptx", "odp",
    "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp",
    "mp4", "mov", "webm", "mp3", "wav",
    "py", "ipynb", "sql", "json", "xml", "yml", "yaml",
    "dwg", "dxf", "fig", "psd", "ai", "apk",
}

BLOCKED_EXTENSIONS = {
    "exe", "msi", "bat", "cmd", "com", "scr", "ps1", "vbs", "js", "jar",
    "dll", "so", "sh", "php", "phtml", "html", "htm",
}

MAX_FILE_BYTES = 32 * 1024 * 1024      # one file
MAX_SUBMISSION_BYTES = 96 * 1024 * 1024  # all files in one version


class UploadError(Exception):
    """Something about the file means it cannot be accepted."""


def _root():
    root = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(root, exist_ok=True)
    return root


def extension_of(filename):
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def check_name(filename):
    ext = extension_of(filename)
    if not ext:
        raise UploadError(f"“{filename}” has no file extension.")
    if ext in BLOCKED_EXTENSIONS:
        raise UploadError(f"“{filename}” is a program file and cannot be uploaded.")
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            f"“{filename}” is not a file type we accept. Put it inside a .zip instead.")
    return ext


def human_size(num_bytes):
    value = float(num_bytes or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def save_submission_file(storage, assignment_id, version):
    """Write one uploaded file to disk.

    Returns the metadata the caller inserts into submission_files. Raises
    UploadError with a message safe to show the student.
    """
    original = storage.filename or ""
    ext = check_name(original)

    data = storage.read()
    if not data:
        raise UploadError(f"“{original}” is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise UploadError(
            f"“{original}” is {human_size(len(data))}. "
            f"The limit for one file is {human_size(MAX_FILE_BYTES)}.")

    folder = os.path.join(_root(), SUBMISSIONS_DIR, str(assignment_id), f"v{version}")
    os.makedirs(folder, exist_ok=True)

    safe_stem = secure_filename(original.rsplit(".", 1)[0])[:60] or "file"
    stored_name = f"{safe_stem}-{secrets.token_hex(6)}.{ext}"
    absolute = os.path.join(folder, stored_name)

    with open(absolute, "wb") as fh:
        fh.write(data)

    relative = os.path.join(
        SUBMISSIONS_DIR, str(assignment_id), f"v{version}", stored_name
    ).replace("\\", "/")

    return {
        "original_name": original[:255],
        "stored_name": stored_name,
        "relative_path": relative,
        "size_bytes": len(data),
        "mime_type": (mimetypes.guess_type(original)[0] or "application/octet-stream")[:120],
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def absolute_path(relative_path):
    """Resolve a stored path, refusing anything that escapes the upload root."""
    root = os.path.realpath(_root())
    target = os.path.realpath(os.path.join(root, relative_path))
    if not target.startswith(root + os.sep):
        raise UploadError("That file path is not valid.")
    if not os.path.isfile(target):
        raise UploadError("That file is no longer on the server.")
    return target


def build_archive(files, folder_name="project"):
    """Zip a list of submission_files rows into memory for download."""
    safe_folder = re.sub(r"[^A-Za-z0-9._-]+", "-", folder_name).strip("-") or "project"
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        used = set()
        for row in files:
            name = secure_filename(row["original_name"]) or row["stored_name"]
            # Two files with the same name in one submission would collide.
            candidate, n = name, 2
            while candidate in used:
                stem, _, ext = name.rpartition(".")
                candidate = f"{stem}-{n}.{ext}" if stem else f"{name}-{n}"
                n += 1
            used.add(candidate)
            archive.write(absolute_path(row["relative_path"]), f"{safe_folder}/{candidate}")

    buffer.seek(0)
    return buffer


def delete_submission_files(rows):
    """Best effort cleanup — a missing file is not an error."""
    for row in rows:
        try:
            os.remove(absolute_path(row["relative_path"]))
        except (OSError, UploadError):
            pass

"""Report submission files whose row exists but whose file is missing.

Run it when a download returns 410. Reads only; changes nothing.

    python check_uploads.py
"""
import os

from app import app
from db import query
import storage


def main():
    with app.app_context():
        print(f"Upload folder: {app.config['UPLOAD_FOLDER']}")
        print(f"Exists: {os.path.isdir(app.config['UPLOAD_FOLDER'])}\n")

        rows = query(
            """SELECT sf.id, sf.original_name, sf.relative_path, sf.uploaded_at,
                      s.version, p.title, u.fullname
                 FROM submission_files sf
                 JOIN submissions s ON s.id = sf.submission_id
                 JOIN assignments a ON a.id = s.assignment_id
                 JOIN projects p ON p.id = a.project_id
                 JOIN users u ON u.id = sf.uploaded_by
                ORDER BY sf.id""")

        missing = []
        for row in rows:
            try:
                storage.absolute_path(row["relative_path"])
            except storage.UploadError:
                missing.append(row)

        print(f"{len(rows)} file record(s), {len(missing)} missing from disk.\n")
        for row in missing:
            print(f"  MISSING  {row['original_name']}")
            print(f"           {row['title']} v{row['version']}, "
                  f"sent by {row['fullname']} on "
                  f"{row['uploaded_at'].strftime('%d %b %Y')}")
            print(f"           expected at {row['relative_path']}\n")

        if missing:
            print("These have to be uploaded again — the content is gone.")
            print("To stop it recurring, point UPLOAD_FOLDER in .env at a path")
            print("outside the project folder, e.g. C:\\praxorax-uploads")


if __name__ == "__main__":
    main()

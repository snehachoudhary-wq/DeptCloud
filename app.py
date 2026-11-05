import os
import time
import uuid
from functools import wraps
from io import BytesIO

import httpx
from dotenv import load_dotenv
from flask import (
    Flask, abort, flash, g, redirect, render_template, request,
    send_file, session, url_for,
)
from supabase import create_client
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "10")) * 1024 * 1024

ALLOWED = {"pdf", "docx", "pptx", "txt", "xlsx"}
BUCKET = "department-files"


# --------------------------------------------------
# SUPABASE CONNECTION AND SESSION MANAGEMENT
# --------------------------------------------------

def _store_auth_session(auth_session):
    if not auth_session:
        return

    session["access_token"] = auth_session.access_token
    session["refresh_token"] = auth_session.refresh_token

    expires_at = getattr(auth_session, "expires_at", None)
    expires_in = getattr(auth_session, "expires_in", None)
    if expires_at:
        session["expires_at"] = int(expires_at)
    elif expires_in:
        session["expires_at"] = int(time.time()) + int(expires_in)
    else:
        session.pop("expires_at", None)


def _new_supabase_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_ANON_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_ANON_KEY in .env")
    return create_client(url, key)


def client():
    """One Supabase client per HTTP request, authenticated for the active user."""
    if hasattr(g, "supabase_client"):
        return g.supabase_client

    sb = _new_supabase_client()
    access_token = session.get("access_token")
    refresh_token = session.get("refresh_token")

    if access_token and refresh_token:
        try:
            # Supabase's set_session can validate/refresh credentials. Keep
            # this rather than using an unverified browser-provided identity.
            auth = sb.auth.set_session(access_token, refresh_token)
            if auth.session:
                _store_auth_session(auth.session)
                g.auth_identity = auth.user
            else:
                session.clear()
        except httpx.RequestError:
            # A temporary connection failure must not log the user out.
            raise
        except Exception as exc:
            # Do not turn an arbitrary server error into an automatic logout.
            # Only explicit authentication failures should clear credentials.
            from supabase_auth.errors import AuthApiError
            if isinstance(exc, AuthApiError) and exc.status in (400, 401, 403):
                app.logger.warning("Supabase rejected session: %s", exc)
                session.clear()
            else:
                raise

    g.supabase_client = sb
    return sb


# --------------------------------------------------
# CURRENT USER
# --------------------------------------------------

def current_user():
    if hasattr(g, "current_profile"):
        return g.current_profile

    if not session.get("access_token"):
        g.current_profile = None
        return None

    sb = client()
    if not session.get("access_token"):
        g.current_profile = None
        return None

    identity = getattr(g, "auth_identity", None)
    if identity is None:
        identity = sb.auth.get_user().user
    if not identity:
        g.current_profile = None
        return None

    profile = (
        sb.table("profiles")
        .select("*")
        .eq("id", identity.id)
        .single()
        .execute()
        .data
    )
    g.current_profile = profile
    return profile


# --------------------------------------------------
# AUTHENTICATION DECORATORS
# --------------------------------------------------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please sign in first.", "warning")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def faculty_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            flash("Please sign in first.", "warning")
            return redirect(url_for("login"))
        if user["role"] not in ("faculty", "admin"):
            abort(403)
        return fn(*args, **kwargs)
    return wrapper


@app.context_processor
def inject_user():
    return {"me": current_user()}


# --------------------------------------------------
# HOME PAGE / DOCUMENT SEARCH
# --------------------------------------------------

@app.route("/")
@login_required
def index():
    sb = client()
    query = sb.table("documents").select("*").order("created_at", desc=True)
    q = request.args.get("q", "").strip()
    subject = request.args.get("subject", "").strip()
    semester = request.args.get("semester", "").strip()

    if q:
        query = query.ilike("title", "%" + q.replace("%", "") + "%")
    if subject:
        query = query.eq("subject", subject)
    if semester:
        query = query.eq("semester", semester)

    docs = query.execute().data
    return render_template("index.html", docs=docs, q=q, subject=subject, semester=semester)


# --------------------------------------------------
# STUDENT REGISTRATION
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        try:
            # Registration should never inherit a different user's session.
            sb = _new_supabase_client()
            sb.auth.sign_up({
                "email": request.form["email"].strip(),
                "password": request.form["password"],
                "options": {"data": {"full_name": request.form["full_name"].strip()}}
            })
            flash(
                "Account created. Confirm your email if required, then sign in. "
                "All new accounts start as students.", "success"
            )
            return redirect(url_for("login"))
        except httpx.RequestError:
            raise
        except Exception as exc:
            app.logger.warning("Registration failed: %s", type(exc).__name__)
            flash("Registration failed. Check the details and try again.", "danger")
    return render_template("auth.html", mode="register")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        try:
            session.clear()
            sb = _new_supabase_client()
            result = sb.auth.sign_in_with_password({
                "email": request.form["email"].strip(),
                "password": request.form["password"]
            })
            if not result.session:
                flash("Unable to create login session.", "danger")
                return redirect(url_for("login"))

            _store_auth_session(result.session)
            flash("Signed in successfully.", "success")
            return redirect(url_for("index"))
        except httpx.RequestError:
            raise
        except Exception as exc:
            app.logger.warning("Sign-in failed: %s", type(exc).__name__)
            flash("Sign-in failed. Check your email and password.", "danger")
    return render_template("auth.html", mode="login")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    g.current_profile = None
    flash("Signed out.", "info")
    return redirect(url_for("login"))


# --------------------------------------------------
# UPLOAD FILE
# --------------------------------------------------

@app.route("/upload", methods=["GET", "POST"])
@faculty_required
def upload():
    if request.method == "POST":
        f = request.files.get("file")
        title = request.form.get("title", "").strip()
        if not f or not f.filename or not title:
            flash("Title and file are required.", "danger")
            return redirect(url_for("upload"))

        name = secure_filename(f.filename)
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED:
            flash("Unsupported file type.", "danger")
            return redirect(url_for("upload"))

        sb = client()
        user = current_user()
        doc_id = str(uuid.uuid4())
        path = f"{doc_id}/v1/{uuid.uuid4().hex}.{ext}"
        try:
            data = f.read()
            sb.storage.from_(BUCKET).upload(
                path, data, {"content-type": f.mimetype or "application/octet-stream"}
            )
            try:
                sb.table("documents").insert({
                    "id": doc_id,
                    "title": title,
                    "subject": request.form["subject"].strip(),
                    "semester": request.form["semester"].strip(),
                    "department": request.form["department"].strip(),
                    "owner_id": user["id"],
                    "latest_version": 1
                }).execute()
                sb.table("file_versions").insert({
                    "document_id": doc_id,
                    "version": 1,
                    "storage_path": path,
                    "original_name": name,
                    "uploaded_by": user["id"]
                }).execute()
            except Exception:
                # Best-effort cleanup; don't hide the original exception.
                try:
                    sb.storage.from_(BUCKET).remove([path])
                    sb.table("documents").delete().eq("id", doc_id).execute()
                except Exception:
                    app.logger.exception("Upload cleanup failed")
                raise
            flash("File uploaded to cloud storage.", "success")
            return redirect(url_for("index"))
        except httpx.RequestError:
            raise
        except Exception as exc:
            app.logger.exception("Upload failed")
            flash("Upload failed. Please try again.", "danger")
    return render_template("upload.html")


# --------------------------------------------------
# DOCUMENT DETAILS / VERSION HISTORY
# --------------------------------------------------

@app.route("/document/<doc_id>")
@login_required
def document(doc_id):
    sb = client()
    doc = sb.table("documents").select("*").eq("id", doc_id).single().execute().data
    if not doc:
        abort(404)
    versions = (
        sb.table("file_versions").select("*")
        .eq("document_id", doc_id).order("version", desc=True)
        .execute().data
    )
    return render_template("document.html", doc=doc, versions=versions)


# --------------------------------------------------
# DOWNLOAD FILE
# --------------------------------------------------

@app.route("/download/<version_id>")
@login_required
def download(version_id):
    sb = client()
    version = (
        sb.table("file_versions").select("*")
        .eq("id", version_id).single().execute().data
    )
    if not version:
        abort(404)
    content = sb.storage.from_(BUCKET).download(version["storage_path"])
    return send_file(
        BytesIO(content), as_attachment=True,
        download_name=version["original_name"],
        mimetype="application/octet-stream"
    )


# --------------------------------------------------
# UPLOAD NEW FILE VERSION
# --------------------------------------------------

@app.route("/document/<doc_id>/new-version", methods=["POST"])
@faculty_required
def new_version(doc_id):
    sb = client()
    user = current_user()
    doc = sb.table("documents").select("*").eq("id", doc_id).single().execute().data
    if not doc:
        abort(404)
    if doc["owner_id"] != user["id"] and user["role"] != "admin":
        abort(403)

    f = request.files.get("file")
    if not f or not f.filename:
        flash("Select a file.", "danger")
        return redirect(url_for("document", doc_id=doc_id))
    name = secure_filename(f.filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        flash("Unsupported file type.", "danger")
        return redirect(url_for("document", doc_id=doc_id))

    next_version = doc["latest_version"] + 1
    path = f"{doc_id}/v{next_version}/{uuid.uuid4().hex}.{ext}"
    try:
        sb.storage.from_(BUCKET).upload(
            path, f.read(), {"content-type": f.mimetype or "application/octet-stream"}
        )
        sb.table("file_versions").insert({
            "document_id": doc_id,
            "version": next_version,
            "storage_path": path,
            "original_name": name,
            "uploaded_by": user["id"]
        }).execute()
        sb.table("documents").update({
            "latest_version": next_version
        }).eq("id", doc_id).execute()
        flash("New version uploaded.", "success")
    except httpx.RequestError:
        raise
    except Exception:
        app.logger.exception("Version upload failed")
        flash("Version upload failed. Please try again.", "danger")
    return redirect(url_for("document", doc_id=doc_id))


# --------------------------------------------------
# ADMIN DASHBOARD
# --------------------------------------------------

@app.route("/admin")
@login_required
def admin():
    user = current_user()
    if user["role"] != "admin":
        abort(403)
    users = (
        client().table("profiles").select("*")
        .order("created_at", desc=True).execute().data
    )
    return render_template("admin.html", users=users)


# --------------------------------------------------
# CHANGE USER ROLE
# --------------------------------------------------

@app.route("/admin/role/<user_id>", methods=["POST"])
@login_required
def set_role(user_id):
    user = current_user()
    if user["role"] != "admin":
        abort(403)
    role = request.form.get("role")
    if role not in ("student", "faculty", "admin"):
        abort(400)
    if user_id == user["id"]:
        flash("You cannot change your own role here.", "warning")
    else:
        client().table("profiles").update({"role": role}).eq("id", user_id).execute()
        flash("User role updated.", "success")
    return redirect(url_for("admin"))


# --------------------------------------------------
# ERROR HANDLERS
# --------------------------------------------------

@app.errorhandler(httpx.RequestError)
def supabase_connection_error(error):
    app.logger.error("Supabase network request failed: %s", error)
    return (
        "Unable to connect to Supabase right now. Please refresh the page "
        "or try again shortly.", 503
    )


@app.errorhandler(413)
def too_large(error):
    return "File exceeds the configured upload size limit.", 413


@app.errorhandler(403)
def forbidden(error):
    return "Access denied. You do not have permission to perform this action.", 403


# --------------------------------------------------
# START APPLICATION
# --------------------------------------------------

if __name__ == "__main__":
    from waitress import serve

    print("Starting DeptCloud...")
    print("DeptCloud running at http://[::1]:8765")

    serve(
        app,
        host="::1",
        port=8765,
        threads=8
    )

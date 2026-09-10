"""
CIVICAI - AI-Powered Civic Issue Detection, Prioritization & Resolution Platform
Smart India Hackathon (SIH) Edition
"""

import os
import math
import uuid
import random
import json
import hashlib
import base64
import urllib.parse
import urllib.request
import urllib.error
import sqlite3
import re
from PIL import Image
from PIL.ExifTags import GPSTAGS
from functools import wraps
from datetime import datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify

from ai_model import analyze_issue

app = Flask(__name__)
app.secret_key = os.environ.get("CIVICAI_SECRET_KEY", "civicai-sih-secret-2026-key")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "civicai.db")

UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
BOUNDARY_PATH = os.path.join(BASE_DIR, "data", "municipal_boundary.geojson")
MUNICIPALITY_NAME = os.environ.get("CIVICAI_MUNICIPALITY", "Prayagraj Metropolitan Municipal Corporation Area")

OTP_TTL_SECONDS = 5 * 60       # 5 minutes
OTP_COOLDOWN_SECONDS = 30      # 30 seconds
OTP_MAX_ATTEMPTS = 3


# =========================================================
# DATABASE CONNECTION & SCHEMA
# =========================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()

    # 1. REPORTS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT,
            description TEXT,
            location TEXT,
            status TEXT DEFAULT 'Pending',
            priority TEXT DEFAULT 'Low',
            department TEXT,
            latitude REAL,
            longitude REAL,
            photo TEXT,
            verification TEXT DEFAULT 'Location Verified',
            supervisor TEXT,
            field_worker TEXT,
            assignment_status TEXT DEFAULT 'Unassigned',
            accepted_at TEXT,
            assigned_at TEXT,
            started_at TEXT,
            resolved_at TEXT,
            expected_visit_date TEXT,
            estimated_completion_date TEXT,
            resolution_note TEXT,
            resolution_photo TEXT,
            resolution_latitude REAL,
            resolution_longitude REAL,
            reporter_id INTEGER,
            reporter_name TEXT,
            created_at TEXT,
            rating INTEGER,
            feedback TEXT,
            feedback_submitted_at TEXT,
            photo_hash TEXT
        )
    """)

    # Check for any missing columns in reports
    existing_report_cols = [r["name"] for r in conn.execute("PRAGMA table_info(reports)").fetchall()]
    report_migrations = {
        "reporter_id": "INTEGER",
        "reporter_name": "TEXT",
        "created_at": "TEXT",
        "expected_visit_date": "TEXT",
        "estimated_completion_date": "TEXT",
        "resolution_note": "TEXT",
        "resolution_photo": "TEXT",
        "resolution_latitude": "REAL",
        "resolution_longitude": "REAL",
        "rating": "INTEGER",
        "feedback": "TEXT",
        "feedback_submitted_at": "TEXT",
        "photo_hash": "TEXT"
    }
    for col, col_type in report_migrations.items():
        if col not in existing_report_cols:
            conn.execute(f"ALTER TABLE reports ADD COLUMN {col} {col_type}")

    # 2. USERS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'citizen',
            staff_role TEXT,
            department TEXT,
            phone TEXT,
            phone_verified INTEGER DEFAULT 0,
            account_number TEXT,
            dob TEXT,
            profile_photo TEXT,
            created_at TEXT NOT NULL
        )
    """)

    existing_user_cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
    user_migrations = {
        "phone_verified": "INTEGER DEFAULT 0",
        "staff_role": "TEXT",
        "department": "TEXT",
        "phone": "TEXT",
        "account_number": "TEXT",
        "dob": "TEXT",
        "profile_photo": "TEXT"
    }
    for col, col_type in user_migrations.items():
        if col not in existing_user_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")

    # 3. DEPARTMENTS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            department TEXT UNIQUE,
            name TEXT,
            phone TEXT
        )
    """)

    departments = [
        ("Road Department", "Road Supervisor", "9000000001"),
        ("Sanitation Department", "Sanitation Supervisor", "9000000002"),
        ("Electrical Department", "Electrical Supervisor", "9000000003"),
        ("Water Supply Department", "Water Supervisor", "9000000004"),
        ("Drainage Department", "Drainage Supervisor", "9000000005"),
        ("Municipal Maintenance Department", "Maintenance Supervisor", "9000000006")
    ]
    for dept, sup_name, phone in departments:
        existing = conn.execute("SELECT id FROM departments WHERE department=?", (dept,)).fetchone()
        if not existing:
            conn.execute("INSERT INTO departments (department, name, phone) VALUES (?, ?, ?)", (dept, sup_name, phone))

    # 4. FIELD WORKERS TABLE
    conn.execute("""
        CREATE TABLE IF NOT EXISTS field_workers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            department TEXT,
            phone TEXT,
            status TEXT DEFAULT 'Available'
        )
    """)

    workers = [
        ("Rahul Sharma", "Road Department", "9100000001", "Available"),
        ("Amit Verma", "Road Department", "9100000002", "Available"),
        ("Rohit Kumar", "Sanitation Department", "9100000003", "Available"),
        ("Vikas Singh", "Electrical Department", "9100000004", "Available"),
        ("Ankit Yadav", "Water Supply Department", "9100000005", "Available"),
        ("Manish Patel", "Drainage Department", "9100000006", "Available"),
        ("Deepak Gupta", "Municipal Maintenance Department", "9100000007", "Available")
    ]
    for w_name, w_dept, w_phone, w_status in workers:
        existing = conn.execute("SELECT id FROM field_workers WHERE name=? AND department=?", (w_name, w_dept)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO field_workers (name, department, phone, status) VALUES (?, ?, ?, ?)",
                (w_name, w_dept, w_phone, w_status)
            )

    # 5. DEMO STAFF ACCOUNTS SEEDING
    # Supervisor account: supervisor / admin123
    existing_sup = conn.execute("SELECT id FROM users WHERE account_number='SUPERVISOR' OR email='supervisor@civicai.gov.in'").fetchone()
    if not existing_sup:
        conn.execute("""
            INSERT INTO users (name, email, password_hash, role, staff_role, department, account_number, created_at)
            VALUES (?, ?, ?, 'department', 'Supervisor', 'All Departments', 'SUPERVISOR', ?)
        """, ("Central Supervisor", "supervisor@civicai.gov.in", generate_password_hash("admin123"), current_time()))

    # Field Worker account: worker.rahul / worker123
    existing_worker = conn.execute("SELECT id FROM users WHERE account_number='WORKER.RAHUL' OR email='rahul@civicai.gov.in'").fetchone()
    if not existing_worker:
        conn.execute("""
            INSERT INTO users (name, email, password_hash, role, staff_role, department, account_number, created_at)
            VALUES (?, ?, ?, 'department', 'Field Worker', 'Road Department', 'WORKER.RAHUL', ?)
        """, ("Rahul Sharma", "rahul@civicai.gov.in", generate_password_hash("worker123"), current_time()))

    # Additional Demo Field Worker: worker.rohit / worker123 (Sanitation)
    existing_rohit = conn.execute("SELECT id FROM users WHERE account_number='WORKER.ROHIT' OR email='rohit@civicai.gov.in'").fetchone()
    if not existing_rohit:
        conn.execute("""
            INSERT INTO users (name, email, password_hash, role, staff_role, department, account_number, created_at)
            VALUES (?, ?, ?, 'department', 'Field Worker', 'Sanitation Department', 'WORKER.ROHIT', ?)
        """, ("Rohit Kumar", "rohit@civicai.gov.in", generate_password_hash("worker123"), current_time()))

    conn.commit()
    conn.close()


# =========================================================
# POINT-IN-POLYGON & MUNICIPAL BOUNDARY VALIDATION
# =========================================================

def _ray_casting_point_in_ring(x, y, ring):
    """Ray casting algorithm for a 2D ring of [x, y] = [lon, lat] points."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


def _point_in_polygon_geometry(lon, lat, polygon_coords):
    """Checks whether (lon, lat) is inside polygon coordinates (with holes)."""
    if not polygon_coords or len(polygon_coords) == 0:
        return False
    # Must be inside the exterior ring
    if not _ray_casting_point_in_ring(lon, lat, polygon_coords[0]):
        return False
    # Must be outside all interior rings (holes)
    for hole in polygon_coords[1:]:
        if _ray_casting_point_in_ring(lon, lat, hole):
            return False
    return True


def is_point_in_service_area(latitude, longitude):
    """
    Validates whether GPS (latitude, longitude) falls inside the supported municipal boundary GeoJSON.
    Returns: (is_inside: bool, municipal_name: str)
    """
    if latitude is None or longitude is None:
        return False, MUNICIPALITY_NAME

    try:
        lat = float(latitude)
        lon = float(longitude)
    except (ValueError, TypeError):
        return False, MUNICIPALITY_NAME

    if not os.path.exists(BOUNDARY_PATH):
        # Fallback to true with logging if boundary file is missing
        return True, MUNICIPALITY_NAME

    try:
        with open(BOUNDARY_PATH, "r", encoding="utf-8") as f:
            geojson = json.load(f)

        features = geojson.get("features", [])
        for feat in features:
            geom = feat.get("geometry", {})
            geom_type = geom.get("type")
            coords = geom.get("coordinates", [])
            props = feat.get("properties", {})
            muni_name = props.get("name", MUNICIPALITY_NAME)

            if geom_type == "Polygon":
                if _point_in_polygon_geometry(lon, lat, coords):
                    return True, muni_name
            elif geom_type == "MultiPolygon":
                for poly in coords:
                    if _point_in_polygon_geometry(lon, lat, poly):
                        return True, muni_name

        return False, MUNICIPALITY_NAME
    except Exception as e:
        print(f"[CIVICAI Error] Error validating boundary: {e}")
        # Fail safe if error
        return False, MUNICIPALITY_NAME


# =========================================================
# AUTHENTICATION & ROLE-BASED ACCESS CONTROL
# =========================================================

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None

    conn = get_db()
    user = conn.execute("""
        SELECT id, name, email, role, staff_role, department, phone,
               phone_verified, account_number, dob, profile_photo, created_at
        FROM users
        WHERE id=?
    """, (user_id,)).fetchone()
    conn.close()

    if user:
        return dict(user)
    return None


def citizen_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user:
            flash("Please verify your mobile number to continue.", "info")
            return redirect(url_for("login", next=request.path))
        if user.get("role") != "citizen":
            flash("Citizen login is required for this action.", "warning")
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view


def staff_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "department":
            flash("Staff login is required to access the operations panel.", "warning")
            return redirect(url_for("staff_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view


def supervisor_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "department":
            flash("Supervisor authorization required.", "warning")
            return redirect(url_for("staff_login", next=request.path))
        if user.get("staff_role") == "Field Worker":
            flash("Access restricted to Supervisors. Redirected to Worker panel.", "info")
            return redirect(url_for("worker"))
        return view(*args, **kwargs)
    return wrapped_view


def worker_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        user = get_current_user()
        if not user or user.get("role") != "department":
            flash("Staff login is required.", "warning")
            return redirect(url_for("staff_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped_view


@app.context_processor
def inject_globals():
    user = get_current_user()
    return {
        "current_user": user,
        "municipality_name": MUNICIPALITY_NAME,
        "current_year": datetime.now().year
    }


# =========================================================
# HELPER FUNCTIONS
# =========================================================

def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_upload(file, prefix="photo"):
    if not file or not file.filename:
        return None
    if not allowed_file(file.filename):
        return None
    original_name = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    filename = f"{prefix}_{timestamp}_{original_name}"
    file_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(file_path)
    return filename


def calculate_distance(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return 999999
    try:
        lat1, lon1, lat2, lon2 = float(lat1), float(lon1), float(lat2), float(lon2)
    except (TypeError, ValueError):
        return 999999

    R = 6371000  # meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_complaint_text(value):
    if value is None:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value).lower())
    return " ".join(normalized.split())


def extract_photo_gps(photo_file):
    """Return the image GPS coordinates when the uploaded photo contains them."""
    try:
        photo_file.stream.seek(0)
        image = Image.open(photo_file.stream)
        exif = image.getexif()
        gps_info = exif.get_ifd(34853) if exif and hasattr(exif, "get_ifd") else {}
        if not gps_info:
            return None

        gps = {GPSTAGS.get(key, key): value for key, value in gps_info.items()}
        latitude = gps.get("GPSLatitude")
        longitude = gps.get("GPSLongitude")
        if not latitude or not longitude:
            return None

        def to_decimal(values, reference):
            degrees, minutes, seconds = [float(item) for item in values]
            decimal = degrees + minutes / 60 + seconds / 3600
            if isinstance(reference, bytes):
                reference = reference.decode("ascii", errors="ignore")
            return -decimal if reference in ("S", "W") else decimal

        return (
            to_decimal(latitude, gps.get("GPSLatitudeRef")),
            to_decimal(longitude, gps.get("GPSLongitudeRef")),
        )
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError):
        return None
    finally:
        photo_file.stream.seek(0)


def complaints_match(description, old_description):
    current = set(normalize_complaint_text(description).split())
    previous = set(normalize_complaint_text(old_description).split())
    if not current or not previous:
        return False
    if current == previous:
        return True
    return len(current & previous) / len(current | previous) >= 0.6


def get_department(category):
    department_map = {
        "Pothole / Damaged Road": "Road Department",
        "Garbage Overflow": "Sanitation Department",
        "Broken Streetlight": "Electrical Department",
        "Water Leakage": "Water Supply Department",
        "Drainage Issue": "Drainage Department",
        "Damaged Public Infrastructure": "Municipal Maintenance Department",
        "Other": "Municipal Maintenance Department"
    }
    return department_map.get(category, "Municipal Maintenance Department")


def get_supervisor(department):
    conn = get_db()
    supervisor = conn.execute(
        "SELECT name FROM departments WHERE department=? LIMIT 1",
        (department,)
    ).fetchone()
    conn.close()
    if supervisor and supervisor["name"]:
        return supervisor["name"]
    return "Central Supervisor"


def generate_otp():
    return f"{random.randint(100000, 999999):06d}"


def hash_otp(phone, otp):
    payload = f"{app.secret_key}:{phone.strip()}:{otp.strip()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def send_otp_sms(phone, otp):
    """
    Sends OTP via Twilio SMS if configured.
    Returns: (sent_successfully: bool, is_demo_mode: bool)
    """
    sid = os.environ.get("TWILIO_ACCOUNT_SID")
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    sender = os.environ.get("TWILIO_FROM_NUMBER")

    if not sid or not token or not sender:
        # Twilio credentials not configured => Dev Demo Mode
        return False, True

    clean_phone = phone.strip()
    if clean_phone.isdigit() and len(clean_phone) == 10:
        clean_phone = "+91" + clean_phone
    elif not clean_phone.startswith("+"):
        clean_phone = "+" + clean_phone

    endpoint = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    payload = urllib.parse.urlencode({
        "To": clean_phone,
        "From": sender,
        "Body": f"CIVICAI Verification Code: {otp}. Valid for 5 minutes. Do not share this code."
    }).encode("utf-8")
    credentials = base64.b64encode(f"{sid}:{token}".encode("utf-8")).decode("ascii")
    sms_request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(sms_request, timeout=8):
            return True, False
    except Exception as e:
        print(f"[CIVICAI Twilio Error] {e}")
        return False, True


# =========================================================
# CITIZEN MOBILE OTP AUTHENTICATION
# =========================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    current = get_current_user()
    if current:
        if current["role"] == "department":
            if current.get("staff_role") == "Field Worker":
                return redirect(url_for("worker"))
            return redirect(url_for("supervisor"))
        return redirect(url_for("home"))

    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "GET":
        return render_template("login.html", next_url=next_url, otp_sent=False)

    action = request.form.get("action", "send_otp")
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()

    # Step 1: Send OTP
    if action == "send_otp":
        if not name:
            flash("Please enter your name.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=False)

        # Normalize phone: extract digits
        digits = "".join([c for c in phone if c.isdigit()])
        if len(digits) < 10:
            flash("Please enter a valid 10-digit mobile number.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=False)
        phone = digits[-10:]

        # Check cooldown
        last_request_time = session.get("otp_requested_at")
        if last_request_time:
            elapsed = (datetime.now() - datetime.fromisoformat(last_request_time)).total_seconds()
            if elapsed < OTP_COOLDOWN_SECONDS:
                remaining = int(OTP_COOLDOWN_SECONDS - elapsed)
                flash(f"Please wait {remaining} seconds before requesting a new OTP.", "warning")
                return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=True,
                                       dev_otp=session.get("dev_otp"))

        # Generate & store OTP hash
        otp = generate_otp()
        expiry = datetime.now() + timedelta(seconds=OTP_TTL_SECONDS)

        session["pending_name"] = name
        session["pending_phone"] = phone
        session["otp_hash"] = hash_otp(phone, otp)
        session["otp_expiry"] = expiry.isoformat()
        session["otp_attempts"] = 0
        session["otp_requested_at"] = datetime.now().isoformat()

        sent, is_demo = send_otp_sms(phone, otp)
        if sent:
            session.pop("dev_otp", None)
            flash(f"Verification code sent to +91 {phone}. Enter it below to login.", "success")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=True)
        else:
            session["dev_otp"] = otp
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=True, dev_otp=otp)

    # Step 2: Verify OTP
    elif action == "verify_otp":
        submitted_otp = request.form.get("otp", "").strip()
        phone = session.get("pending_phone", phone)
        name = session.get("pending_name", name)

        if not submitted_otp or len(submitted_otp) != 6 or not submitted_otp.isdigit():
            flash("Please enter a valid 6-digit OTP.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=True,
                                   dev_otp=session.get("dev_otp"))

        # Check expiration
        expiry_iso = session.get("otp_expiry")
        if not expiry_iso or datetime.now() > datetime.fromisoformat(expiry_iso):
            flash("OTP has expired. Please request a new verification code.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=False)

        # Check attempts
        attempts = session.get("otp_attempts", 0) + 1
        session["otp_attempts"] = attempts
        if attempts > OTP_MAX_ATTEMPTS:
            session.pop("otp_hash", None)
            flash("Too many failed attempts. Please request a new OTP.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=False)

        # Verify hash
        expected_hash = session.get("otp_hash")
        actual_hash = hash_otp(phone, submitted_otp)

        if actual_hash != expected_hash:
            remaining = OTP_MAX_ATTEMPTS - attempts
            flash(f"Invalid verification code. {remaining} attempt(s) remaining.", "error")
            return render_template("login.html", next_url=next_url, phone=phone, name=name, otp_sent=True,
                                   dev_otp=session.get("dev_otp"))

        # Successful OTP verification: find or create citizen
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE phone=? AND role='citizen' LIMIT 1", (phone,)).fetchone()

        if user:
            user_id = user["id"]
            # Update name if changed
            if name and name != user["name"]:
                conn.execute("UPDATE users SET name=?, phone_verified=1 WHERE id=?", (name, user_id))
            else:
                conn.execute("UPDATE users SET phone_verified=1 WHERE id=?", (user_id,))
            conn.commit()
        else:
            cursor = conn.execute("""
                INSERT INTO users (name, email, password_hash, role, phone, phone_verified, created_at)
                VALUES (?, ?, ?, 'citizen', ?, 1, ?)
            """, (name, f"citizen-{uuid.uuid4().hex[:8]}@civicai.local", generate_password_hash(uuid.uuid4().hex), phone, current_time()))
            user_id = cursor.lastrowid
            account_number = f"CITIZEN-{user_id:04d}"
            conn.execute("UPDATE users SET account_number=? WHERE id=?", (account_number, user_id))
            conn.commit()

        conn.close()

        # Clean session
        session.clear()
        session["user_id"] = user_id
        session["user_role"] = "citizen"

        flash("âœ“ Mobile number verified successfully. Welcome to CIVICAI!", "success")
        if next_url and next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
            return redirect(next_url)
        return redirect(url_for("home"))

    return redirect(url_for("login"))


@app.route("/resend-otp", methods=["POST"])
def resend_otp():
    phone = session.get("pending_phone")
    name = session.get("pending_name")

    if not phone or not name:
        flash("Please enter your name and mobile number first.", "warning")
        return redirect(url_for("login"))

    # Cooldown check
    last_request_time = session.get("otp_requested_at")
    if last_request_time:
        elapsed = (datetime.now() - datetime.fromisoformat(last_request_time)).total_seconds()
        if elapsed < OTP_COOLDOWN_SECONDS:
            remaining = int(OTP_COOLDOWN_SECONDS - elapsed)
            flash(f"Please wait {remaining} seconds before requesting a new OTP.", "warning")
            return redirect(url_for("login"))

    otp = generate_otp()
    expiry = datetime.now() + timedelta(seconds=OTP_TTL_SECONDS)
    session["otp_hash"] = hash_otp(phone, otp)
    session["otp_expiry"] = expiry.isoformat()
    session["otp_attempts"] = 0
    session["otp_requested_at"] = datetime.now().isoformat()

    sent, is_demo = send_otp_sms(phone, otp)
    if sent:
        session.pop("dev_otp", None)
        flash(f"New OTP sent to +91 {phone}.", "success")
    else:
        session["dev_otp"] = otp
        flash("A new demo OTP has been generated.", "info")

    return redirect(url_for("login"))


@app.route("/register", methods=["GET", "POST"])
def register():
    # Citizen registration is unified with instant Mobile OTP Login
    return redirect(url_for("login"))


# =========================================================
# SEPARATE STAFF / DEPARTMENT LOGIN
# =========================================================

@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    current = get_current_user()
    if current and current["role"] == "department":
        if current.get("staff_role") == "Field Worker":
            return redirect(url_for("worker"))
        return redirect(url_for("supervisor"))

    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "GET":
        return render_template("staff_login.html", next_url=next_url)

    username = request.form.get("username", "").strip()
    password = request.form.get("password", "").strip()

    if not username or not password:
        flash("Please enter both staff username and password.", "error")
        return render_template("staff_login.html", next_url=next_url, username=username)

    conn = get_db()
    # Support username matching account_number, email, or exact name
    user = conn.execute("""
        SELECT * FROM users
        WHERE (LOWER(account_number)=LOWER(?)
            OR LOWER(email)=LOWER(?)
            OR LOWER(name)=LOWER(?))
          AND role='department'
        LIMIT 1
    """, (username, username, username)).fetchone()
    conn.close()

    if not user or not user["password_hash"] or not check_password_hash(user["password_hash"], password):
        flash("Invalid staff credentials. Please check your username and password.", "error")
        return render_template("staff_login.html", next_url=next_url, username=username)

    session.clear()
    session["user_id"] = user["id"]
    session["user_role"] = "department"

    flash(f"Welcome back, {user['name']} ({user['staff_role'] or 'Staff'}).", "success")

    if next_url and next_url.startswith("/") and not next_url.startswith(("//", "/\\")):
        return redirect(next_url)

    if user["staff_role"] == "Field Worker":
        return redirect(url_for("worker"))
    return redirect(url_for("supervisor"))


@app.route("/staff/register", methods=["GET", "POST"])
def staff_register():
    # Keep department staff registration available for expanding municipality teams
    conn = get_db()
    departments = conn.execute("SELECT department FROM departments ORDER BY department").fetchall()
    conn.close()

    if request.method == "GET":
        return render_template("staff_register.html", departments=departments)

    name = request.form.get("name", "").strip()
    department = request.form.get("department", "").strip()
    staff_role = request.form.get("staff_role", "").strip()
    phone = request.form.get("phone", "").strip()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    valid_depts = [row["department"] for row in departments]

    if not name or department not in valid_depts or staff_role not in ["Supervisor", "Field Worker"] or not password:
        flash("Please complete all required fields.", "error")
        return render_template("staff_register.html", departments=departments)

    if len(password) < 6:
        flash("Password must be at least 6 characters long.", "error")
        return render_template("staff_register.html", departments=departments)

    if password != confirm_password:
        flash("Passwords do not match.", "error")
        return render_template("staff_register.html", departments=departments)

    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO users (name, email, password_hash, role, department, staff_role, phone, created_at)
        VALUES (?, ?, ?, 'department', ?, ?, ?, ?)
    """, (name, f"staff-{uuid.uuid4().hex[:8]}@civicai.local", generate_password_hash(password),
          department, staff_role, phone, current_time()))

    account_number = f"DEPT-{cursor.lastrowid:04d}"
    conn.execute("UPDATE users SET account_number=? WHERE id=?", (account_number, cursor.lastrowid))

    # Also register in field_workers if worker
    if staff_role == "Field Worker":
        conn.execute("""
            INSERT INTO field_workers (name, department, phone, status)
            VALUES (?, ?, ?, 'Available')
        """, (name, department, phone))

    conn.commit()
    conn.close()

    flash(f"Department account created! Login Username: {account_number}", "success")
    return redirect(url_for("staff_login"))


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out securely.", "info")
    return redirect(url_for("home"))


# =========================================================
# CITIZEN HOME PAGE
# =========================================================

@app.route("/")
def home():
    current = get_current_user()
    if not current:
        return redirect(url_for("login"))
    if current["role"] == "department":
        if current.get("staff_role") == "Field Worker":
            return redirect(url_for("worker"))
        return redirect(url_for("supervisor"))

    conn = get_db()
    stats = {
        "total": conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"],
        "resolved": conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Resolved'").fetchone()["c"],
        "in_progress": conn.execute("""
            SELECT COUNT(*) AS c FROM reports
            WHERE status IN ('Accepted', 'Assigned', 'In Progress', 'Resolution Submitted')
        """).fetchone()["c"],
        "pending": conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Pending'").fetchone()["c"]
    }
    conn.close()
    return render_template("index.html", stats=stats, citizen_home=True)


@app.route("/public")
def public_home():
    return redirect(url_for("home"))


@app.route("/portal")
def portal():
    return render_template("portal.html")


@app.route("/government")
def government():
    return redirect(url_for("staff_login"))


# =========================================================
# API: GEOJSON SERVICE BOUNDARY
# =========================================================

@app.route("/api/service-boundary")
def api_service_boundary():
    if os.path.exists(BOUNDARY_PATH):
        try:
            with open(BOUNDARY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"error": "Boundary not found"}), 404


# =========================================================
# CITIZEN COMPLAINT REPORTING
# =========================================================

@app.route("/report", methods=["GET", "POST"])
@citizen_required
def report():
    if request.method == "GET":
        return render_template("report.html")

    category_input = request.form.get("category", "").strip()
    description = request.form.get("description", "").strip()
    location_text = request.form.get("location", "").strip()
    latitude_str = request.form.get("latitude", "").strip()
    longitude_str = request.form.get("longitude", "").strip()
    photo_file = request.files.get("photo")

    # 1. Validation of fields
    if not description:
        flash("Please provide a description of the civic issue.", "error")
        return redirect(url_for("report"))

    try:
        latitude = float(latitude_str) if latitude_str else None
        longitude = float(longitude_str) if longitude_str else None
    except (ValueError, TypeError):
        latitude = None
        longitude = None

    if latitude is None or longitude is None:
        flash("GPS location is required. Please click 'Use My Current Location'.", "error")
        return redirect(url_for("report"))

    if not photo_file or not photo_file.filename or not allowed_file(photo_file.filename):
        flash("Please upload a valid issue photo (JPG, JPEG, PNG, or WEBP).", "error")
        return redirect(url_for("report"))

    # 2. AI ISSUE CLASSIFICATION & PRIORITY RECOMMENDATION
    ai_category, priority, ai_department = analyze_issue(description)
    # Prefer selected category if specific, or use AI if 'Other'
    final_category = category_input if (category_input and category_input != "Other") else ai_category
    department = get_department(final_category)
    supervisor = get_supervisor(department)

    # 3. Require embedded photo GPS. This rejects downloaded/Google photos and
    # screenshots because they normally contain no camera location metadata.
    photo_gps = extract_photo_gps(photo_file)
    if not photo_gps:
        return render_template(
            "report.html",
            invalid_photo=True,
            missing_photo_gps=True,
            photo_alert=True
        )
    photo_distance = calculate_distance(latitude, longitude, *photo_gps)
    if photo_distance > 250:
        return render_template(
            "report.html",
            invalid_photo=True,
            photo_distance=int(photo_distance),
            photo_alert=True
        )

    # 4. PHOTO HASH + SAVE
    # Exact SHA-256 hash lets CIVICAI detect the same uploaded photo again.
    try:
        photo_file.stream.seek(0)
        photo_bytes = photo_file.stream.read()
        photo_file.stream.seek(0)
        photo_hash = hashlib.sha256(photo_bytes).hexdigest()
    except Exception:
        photo_hash = None

    # 5. CROSS-CITIZEN DUPLICATE CHECK
    # One active complaint represents the same issue for everyone nearby.
    conn = get_db()
    existing_reports = conn.execute("""
        SELECT * FROM reports
        WHERE category=?
          AND status NOT IN ('Resolved', 'Rejected')
          AND latitude IS NOT NULL AND longitude IS NOT NULL
        ORDER BY id DESC
    """, (final_category,)).fetchall()

    duplicate_match = None
    duplicate_distance = None
    current_reporter_id = get_current_user()["id"]
    for old in existing_reports:
        dist = calculate_distance(latitude, longitude, old["latitude"], old["longitude"])
        same_photo = bool(photo_hash and old["photo_hash"] == photo_hash)
        same_issue = complaints_match(description, old["description"])
        if old["reporter_id"] != current_reporter_id and dist <= 50 and (same_photo or same_issue):
            duplicate_match = old
            duplicate_distance = dist
            break

    if duplicate_match:
        try:
            created_at = datetime.strptime(duplicate_match["created_at"], "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            created_at = datetime.now()
        age_days = (datetime.now() - created_at).days
        if age_days < 10:
            conn.close()
            return render_template(
                "track.html",
                report=dict(duplicate_match),
                report_id=duplicate_match["id"],
                created=False,
                duplicate_detected=True,
                siren_required=True,
                duplicate_distance=int(duplicate_distance or 0),
                retry_after_days=10 - age_days
            )

    photo_filename = save_upload(photo_file, "complaint")

    # 6. INSERT COMPLAINT
    user = get_current_user()
    if not location_text:
        location_text = f"{latitude:.6f}, {longitude:.6f}"

    cursor = conn.execute("""
        INSERT INTO reports (
            category, description, location, status, priority, department,
            latitude, longitude, photo, verification, supervisor, assignment_status,
            reporter_id, reporter_name, created_at, photo_hash
        ) VALUES (?, ?, ?, 'Pending', ?, ?, ?, ?, ?, 'Location Verified', ?, 'Unassigned', ?, ?, ?, ?)
    """, (
        final_category, description, location_text, priority, department,
        latitude, longitude, photo_filename, supervisor,
        user["id"], user["name"], current_time(), photo_hash
    ))
    report_id = cursor.lastrowid
    conn.commit()

    new_report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    conn.close()

    return render_template(
        "track.html",
        report=dict(new_report),
        report_id=report_id,
        created=True,
        duplicate_detected=False,
        siren_required=False
    )


# =========================================================
# CITIZEN COMPLAINT TRACKING & FEEDBACK
# =========================================================

@app.route("/track", methods=["GET", "POST"])
def track():
    report = None
    searched_id = None

    if request.method == "POST":
        raw_id = request.form.get("complaint_id", "").strip().upper()
        clean_id = raw_id.replace("CIVIC-", "").replace("#", "").strip()
        searched_id = raw_id

        try:
            report_id = int(clean_id)
        except (ValueError, TypeError):
            flash("Invalid Complaint ID format. Example: CIVIC-0001", "error")
            return render_template("track.html", report=None, searched_id=searched_id)

        conn = get_db()
        row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        conn.close()

        if not row:
            flash(f"Complaint CIVIC-{report_id:04d} not found.", "error")
            return render_template("track.html", report=None, searched_id=searched_id)

        report = dict(row)

    return render_template("track.html", report=report, searched_id=searched_id)


@app.route("/track-complaint", methods=["POST"])
def track_complaint():
    return track()


@app.route("/track/<complaint_id>")
def track_complaint_get(complaint_id):
    clean_id = complaint_id.upper().replace("CIVIC-", "").replace("#", "").strip()
    try:
        report_id = int(clean_id)
    except (ValueError, TypeError):
        flash("Invalid Complaint ID.", "error")
        return redirect(url_for("track"))

    conn = get_db()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    conn.close()

    if not row:
        flash(f"Complaint CIVIC-{report_id:04d} not found.", "error")
        return redirect(url_for("track"))

    return render_template("track.html", report=dict(row), searched_id=f"CIVIC-{report_id:04d}")


@app.route("/submit-feedback/<int:report_id>", methods=["POST"])
@citizen_required
def submit_feedback(report_id):
    rating_val = request.form.get("rating", "").strip()
    feedback_text = request.form.get("feedback", "").strip()

    try:
        rating = int(rating_val)
        if rating < 1 or rating > 5:
            raise ValueError()
    except (ValueError, TypeError):
        flash("Please select a valid star rating (1 to 5 stars).", "error")
        return redirect(url_for("track_complaint_get", complaint_id=f"CIVIC-{report_id:04d}"))

    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()

    if not report:
        conn.close()
        flash("Complaint not found.", "error")
        return redirect(url_for("track"))

    if report["status"] != "Resolved":
        conn.close()
        flash("Feedback can only be submitted after the complaint has been resolved.", "warning")
        return redirect(url_for("track_complaint_get", complaint_id=f"CIVIC-{report_id:04d}"))

    if report["rating"] is not None:
        conn.close()
        flash("You have already submitted feedback for this complaint. Thank you!", "info")
        return redirect(url_for("track_complaint_get", complaint_id=f"CIVIC-{report_id:04d}"))

    conn.execute("""
        UPDATE reports
        SET rating=?, feedback=?, feedback_submitted_at=?
        WHERE id=?
    """, (rating, feedback_text, current_time(), report_id))
    conn.commit()
    conn.close()

    flash("Thank you! Your feedback helps us improve civic services.", "success")
    return redirect(url_for("track_complaint_get", complaint_id=f"CIVIC-{report_id:04d}"))


@app.route("/complaint/<int:report_id>/receipt")
def complaint_receipt(report_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    conn.close()
    if not row:
        flash("Complaint not found.", "error")
        return redirect(url_for("track"))
    return render_template("receipt.html", report=dict(row))


# =========================================================
# SUPERVISOR CONTROL CENTER & WORKFLOW
# =========================================================

@app.route("/supervisor")
@supervisor_required
def supervisor():
    conn = get_db()
    departments = conn.execute("SELECT * FROM departments ORDER BY department").fetchall()

    dept_filter = request.args.get("department", "").strip()
    priority_filter = request.args.get("priority", "").strip()
    status_filter = request.args.get("status", "").strip()
    category_filter = request.args.get("category", "").strip()
    search_q = request.args.get("q", "").strip().lower()

    query = "SELECT * FROM reports WHERE 1=1"
    params = []

    if dept_filter:
        query += " AND department=?"
        params.append(dept_filter)
    if priority_filter:
        query += " AND priority=?"
        params.append(priority_filter)
    if status_filter:
        query += " AND status=?"
        params.append(status_filter)
    if category_filter:
        query += " AND category=?"
        params.append(category_filter)
    if search_q:
        query += " AND (LOWER(description) LIKE ? OR LOWER(location) LIKE ? OR id LIKE ?)"
        like_term = f"%{search_q}%"
        params.extend([like_term, like_term, like_term])

    query += """
        ORDER BY
            CASE status
                WHEN 'Resolution Submitted' THEN 1
                WHEN 'Pending' THEN 2
                WHEN 'Accepted' THEN 3
                WHEN 'In Progress' THEN 4
                WHEN 'Assigned' THEN 5
                ELSE 6
            END,
            CASE priority
                WHEN 'High' THEN 1
                WHEN 'Medium' THEN 2
                ELSE 3
            END,
            id DESC
    """

    reports = conn.execute(query, params).fetchall()
    reports_list = [dict(r) for r in reports]

    # Field workers for assignment dropdown
    workers = conn.execute("""
        SELECT * FROM field_workers
        ORDER BY department, CASE WHEN status='Available' THEN 1 ELSE 2 END, name
    """).fetchall()

    # Calculate statistics
    total_count = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
    pending_count = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Pending'").fetchone()["c"]
    high_count = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE priority='High' AND status!='Resolved'").fetchone()["c"]
    progress_count = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status IN ('Accepted', 'Assigned', 'In Progress')").fetchone()["c"]
    res_submitted_count = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Resolution Submitted'").fetchone()["c"]
    resolved_count = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Resolved'").fetchone()["c"]

    conn.close()

    return render_template(
        "supervisor.html",
        reports=reports_list,
        workers=[dict(w) for w in workers],
        departments=[dict(d) for d in departments],
        selected_department=dept_filter,
        selected_priority=priority_filter,
        selected_status=status_filter,
        selected_category=category_filter,
        search_q=search_q,
        stats={
            "total": total_count,
            "pending": pending_count,
            "high": high_count,
            "in_progress": progress_count,
            "resolution_submitted": res_submitted_count,
            "resolved": resolved_count
        }
    )


@app.route("/accept-complaint/<int:report_id>", methods=["POST"])
@supervisor_required
def accept_complaint(report_id):
    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    if not report:
        conn.close()
        flash("Complaint not found.", "error")
        return redirect(url_for("supervisor"))

    user = get_current_user()
    supervisor_name = user["name"] if user else get_supervisor(report["department"])
    accepted_at = datetime.now()
    expected_visit = (accepted_at + timedelta(days=2)).strftime("%d %b %Y")
    est_completion = (accepted_at + timedelta(days=3)).strftime("%d %b %Y")

    conn.execute("""
        UPDATE reports
        SET status='Accepted',
            assignment_status='Accepted',
            supervisor=?,
            accepted_at=?,
            expected_visit_date=?,
            estimated_completion_date=?
        WHERE id=?
    """, (supervisor_name, current_time(), expected_visit, est_completion, report_id))
    conn.commit()
    conn.close()

    flash(f"Complaint CIVIC-{report_id:04d} accepted. Please assign a field worker.", "success")
    return redirect(request.referrer or url_for("supervisor"))


@app.route("/assign-worker/<int:report_id>", methods=["POST"])
@supervisor_required
def assign_worker(report_id):
    worker_id = request.form.get("worker_id")
    if not worker_id:
        flash("Please select a field worker to assign.", "error")
        return redirect(request.referrer or url_for("supervisor"))

    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
    worker = conn.execute("SELECT * FROM field_workers WHERE id=?", (worker_id,)).fetchone()

    if not report or not worker:
        conn.close()
        flash("Complaint or worker record not found.", "error")
        return redirect(url_for("supervisor"))

    conn.execute("""
        UPDATE reports
        SET field_worker=?,
            assignment_status='Assigned',
            status='Assigned',
            assigned_at=?,
            expected_visit_date=?,
            estimated_completion_date=?
        WHERE id=?
    """, (
        worker["name"],
        current_time(),
        (datetime.now() + timedelta(days=1)).strftime("%d %b %Y"),
        (datetime.now() + timedelta(days=2)).strftime("%d %b %Y"),
        report_id
    ))

    conn.execute("UPDATE field_workers SET status='Assigned' WHERE id=?", (worker_id,))
    conn.commit()
    conn.close()

    flash(f"Assigned {worker['name']} to Complaint CIVIC-{report_id:04d}.", "success")
    return redirect(request.referrer or url_for("supervisor"))


@app.route("/verify-resolution/<int:report_id>", methods=["POST"])
@supervisor_required
def verify_resolution(report_id):
    action = request.form.get("action", "").strip()
    conn = get_db()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()

    if not report:
        conn.close()
        flash("Complaint not found.", "error")
        return redirect(url_for("supervisor"))

    if action == "approve":
        conn.execute("""
            UPDATE reports
            SET status='Resolved',
                verification='Approved (Supervisor Verified)',
                assignment_status='Resolved',
                resolved_at=?
            WHERE id=?
        """, (current_time(), report_id))

        if report["field_worker"]:
            conn.execute("UPDATE field_workers SET status='Available' WHERE name=?", (report["field_worker"],))

        conn.commit()
        conn.close()
        flash(f"Complaint CIVIC-{report_id:04d} verified and marked as RESOLVED.", "success")

    elif action == "reject":
        conn.execute("""
            UPDATE reports
            SET status='In Progress',
                verification='Revision Required',
                assignment_status='In Progress'
            WHERE id=?
        """, (report_id,))
        conn.commit()
        conn.close()
        flash(f"Resolution for CIVIC-{report_id:04d} returned to worker for revision.", "warning")
    else:
        conn.close()
        flash("Invalid action.", "error")

    return redirect(request.referrer or url_for("supervisor"))


# =========================================================
# FIELD WORKER DASHBOARD & ACTIONS
# =========================================================

@app.route("/worker")
@worker_required
def worker():
    user = get_current_user()
    worker_name = user["name"] if user else ""

    conn = get_db()
    # FIELD WORKER SEES ONLY COMPLAINTS ASSIGNED TO THEM
    assigned_reports = conn.execute("""
        SELECT * FROM reports
        WHERE field_worker=?
          AND status IN ('Assigned', 'In Progress', 'Resolution Submitted')
        ORDER BY
            CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            id DESC
    """, (worker_name,)).fetchall()

    conn.close()
    return render_template(
        "worker.html",
        reports=[dict(r) for r in assigned_reports],
        worker_user=user
    )


@app.route("/start-work/<int:report_id>", methods=["POST"])
@worker_required
def start_work(report_id):
    conn = get_db()
    user = get_current_user()
    report = conn.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()

    if not report:
        conn.close()
        flash("Complaint not found.", "error")
        return redirect(url_for("worker"))

    conn.execute("""
        UPDATE reports
        SET status='In Progress',
            assignment_status='In Progress',
            started_at=?
        WHERE id=?
    """, (current_time(), report_id))
    conn.commit()
    conn.close()

    flash(f"Work started for CIVIC-{report_id:04d}.", "success")
    return redirect(url_for("worker"))


@app.route("/submit-resolution/<int:report_id>", methods=["POST"])
@worker_required
def submit_resolution(report_id):
    note = request.form.get("resolution_note", "").strip()
    lat_str = request.form.get("resolution_latitude", "").strip()
    lon_str = request.form.get("resolution_longitude", "").strip()
    photo = request.files.get("resolution_photo")

    try:
        res_lat = float(lat_str) if lat_str else None
        res_lon = float(lon_str) if lon_str else None
    except (ValueError, TypeError):
        res_lat = None
        res_lon = None

    if not note and not photo:
        flash("Please provide either a completion note or resolution photo.", "error")
        return redirect(url_for("worker"))

    resolution_photo = save_upload(photo, "resolution") if photo else None

    conn = get_db()
    conn.execute("""
        UPDATE reports
        SET status='Resolution Submitted',
            assignment_status='Resolution Submitted',
            verification='Pending Verification',
            resolution_note=?,
            resolution_photo=?,
            resolution_latitude=?,
            resolution_longitude=?
        WHERE id=?
    """, (note, resolution_photo, res_lat, res_lon, report_id))
    conn.commit()
    conn.close()

    flash(f"Resolution submitted for CIVIC-{report_id:04d}. Supervisor will verify the work.", "success")
    return redirect(url_for("worker"))


# =========================================================
# STAFF ANALYTICS & DASHBOARD (SUPERVISOR / ADMIN)
# =========================================================

@app.route("/dashboard")
@supervisor_required
def dashboard():
    conn = get_db()

    reports = conn.execute("""
        SELECT * FROM reports
        ORDER BY
            CASE priority WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            id DESC
    """).fetchall()
    reports_list = [dict(r) for r in reports]

    # Stats
    total = conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
    pending = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Pending'").fetchone()["c"]
    progress = conn.execute("""
        SELECT COUNT(*) AS c FROM reports
        WHERE status IN ('Accepted', 'Assigned', 'In Progress', 'Resolution Submitted')
    """).fetchone()["c"]
    resolved = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE status='Resolved'").fetchone()["c"]
    high_priority = conn.execute("SELECT COUNT(*) AS c FROM reports WHERE priority='High' AND status!='Resolved'").fetchone()["c"]

    # Category chart
    category_rows = conn.execute("""
        SELECT COALESCE(category, 'Unknown') AS category, COUNT(*) AS total
        FROM reports GROUP BY category ORDER BY total DESC
    """).fetchall()
    category_labels = [r["category"] for r in category_rows]
    category_values = [r["total"] for r in category_rows]

    # Status chart
    status_rows = conn.execute("""
        SELECT COALESCE(status, 'Unknown') AS status, COUNT(*) AS total
        FROM reports GROUP BY status ORDER BY total DESC
    """).fetchall()
    status_labels = [r["status"] for r in status_rows]
    status_values = [r["total"] for r in status_rows]

    # Priority chart
    priority_rows = conn.execute("""
        SELECT COALESCE(priority, 'Low') AS priority, COUNT(*) AS total
        FROM reports GROUP BY priority
    """).fetchall()
    priority_labels = [r["priority"] for r in priority_rows]
    priority_values = [r["total"] for r in priority_rows]

    # Department chart
    dept_rows = conn.execute("""
        SELECT COALESCE(department, 'Unassigned') AS department, COUNT(*) AS total
        FROM reports GROUP BY department ORDER BY total DESC
    """).fetchall()
    dept_labels = [r["department"] for r in dept_rows]
    dept_values = [r["total"] for r in dept_rows]

    # CITIZEN FEEDBACK & SATISFACTION ANALYTICS
    feedback_stats = conn.execute("""
        SELECT
            COUNT(rating) AS total_feedbacks,
            AVG(rating) AS avg_rating,
            SUM(CASE WHEN rating=5 THEN 1 ELSE 0 END) AS star5,
            SUM(CASE WHEN rating=4 THEN 1 ELSE 0 END) AS star4,
            SUM(CASE WHEN rating=3 THEN 1 ELSE 0 END) AS star3,
            SUM(CASE WHEN rating=2 THEN 1 ELSE 0 END) AS star2,
            SUM(CASE WHEN rating=1 THEN 1 ELSE 0 END) AS star1
        FROM reports
        WHERE rating IS NOT NULL
    """).fetchone()

    # Department-wise rating
    dept_ratings = conn.execute("""
        SELECT department, ROUND(AVG(rating), 1) as avg_rating, COUNT(rating) as count
        FROM reports
        WHERE rating IS NOT NULL
        GROUP BY department
        ORDER BY avg_rating DESC
    """).fetchall()

    # Recent feedbacks
    recent_feedbacks = conn.execute("""
        SELECT id, category, department, rating, feedback, feedback_submitted_at, reporter_name
        FROM reports
        WHERE rating IS NOT NULL
        ORDER BY id DESC
        LIMIT 8
    """).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        reports=reports_list,
        total=total,
        pending=pending,
        progress=progress,
        resolved=resolved,
        high_priority=high_priority,
        category_labels=category_labels,
        category_values=category_values,
        status_labels=status_labels,
        status_values=status_values,
        priority_labels=priority_labels,
        priority_values=priority_values,
        department_labels=dept_labels,
        department_values=dept_values,
        feedback_summary={
            "total": feedback_stats["total_feedbacks"] or 0,
            "avg": round(feedback_stats["avg_rating"] or 0, 1),
            "star5": feedback_stats["star5"] or 0,
            "star4": feedback_stats["star4"] or 0,
            "star3": feedback_stats["star3"] or 0,
            "star2": feedback_stats["star2"] or 0,
            "star1": feedback_stats["star1"] or 0,
        },
        dept_ratings=[dict(d) for d in dept_ratings],
        recent_feedbacks=[dict(f) for f in recent_feedbacks]
    )


# =========================================================
# APPLICATION ENTRYPOINT
# =========================================================
init_db()

if __name__ == "__main__":
    app.run(
        debug=True,
        host="127.0.0.1",
        port=5000
    )


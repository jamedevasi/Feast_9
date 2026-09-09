"""
Feast9 — database layer.

Single-file SQLite database (see app.config.DB_PATH). Every function opens
its own short-lived connection — simple and safe under Flask's
multi-request/multi-thread dev and prod servers alike (SQLite handles many
short connections fine; this app is single-practitioner scale).
"""
import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime, timedelta

from app.config import DB_PATH
from app.validators import today_iso, now_iso
from app.constants import DEFAULT_PROCEDURE_TYPES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    username             TEXT NOT NULL UNIQUE,
    password_hash        TEXT NOT NULL,
    security_question    TEXT NOT NULL DEFAULT '',
    security_answer_hash TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS doctors (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    active    INTEGER NOT NULL DEFAULT 1,
    color     TEXT NOT NULL DEFAULT '#1E88E5',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS appointments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    case_id     INTEGER REFERENCES cases(id) ON DELETE SET NULL,
    doctor_id   INTEGER REFERENCES doctors(id),
    appt_date   TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT,
    title       TEXT,
    notes       TEXT,
    status      TEXT NOT NULL DEFAULT 'Scheduled',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_appt_date ON appointments(appt_date);
CREATE INDEX IF NOT EXISTS idx_appt_patient ON appointments(patient_id);
CREATE INDEX IF NOT EXISTS idx_appt_doctor ON appointments(doctor_id);

CREATE TABLE IF NOT EXISTS procedure_types (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name      TEXT NOT NULL UNIQUE,
    active    INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS patients (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL,
    age               INTEGER,
    sex               TEXT,
    mobile            TEXT NOT NULL,
    email             TEXT,
    address           TEXT,
    last_visited_date TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    is_historic_import INTEGER NOT NULL DEFAULT 0,
    medical_conditions_json TEXT NOT NULL DEFAULT '[]',
    medical_conditions_other TEXT NOT NULL DEFAULT '',
    is_pregnant       INTEGER NOT NULL DEFAULT 0,
    is_nursing        INTEGER NOT NULL DEFAULT 0,
    allergies_json    TEXT NOT NULL DEFAULT '[]',
    allergies_other   TEXT NOT NULL DEFAULT '',
    emergency_contact_name     TEXT NOT NULL DEFAULT '',
    emergency_contact_relation TEXT NOT NULL DEFAULT '',
    emergency_contact_number   TEXT NOT NULL DEFAULT '',
    dpdp_notice_accepted       INTEGER NOT NULL DEFAULT 0,
    dpdp_notice_accepted_at    TEXT NOT NULL DEFAULT '',
    comms_consent              INTEGER NOT NULL DEFAULT 0,
    comms_consent_at           TEXT NOT NULL DEFAULT '',
    guardian_name              TEXT NOT NULL DEFAULT '',
    guardian_relation          TEXT NOT NULL DEFAULT '',
    guardian_mobile            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_patients_name ON patients(name);
CREATE INDEX IF NOT EXISTS idx_patients_mobile ON patients(mobile);

CREATE TABLE IF NOT EXISTS cases (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id          INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    title               TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'Active',
    procedures_json     TEXT NOT NULL DEFAULT '[]',
    custom_procedure    TEXT,
    doctor_id           INTEGER REFERENCES doctors(id),
    total_cost          REAL NOT NULL DEFAULT 0,
    next_action_note    TEXT,
    follow_up_date      TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    closed_at           TEXT
);
CREATE INDEX IF NOT EXISTS idx_cases_patient ON cases(patient_id);
CREATE INDEX IF NOT EXISTS idx_cases_status ON cases(status);
CREATE INDEX IF NOT EXISTS idx_cases_followup ON cases(follow_up_date);

CREATE TABLE IF NOT EXISTS payments (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    amount      REAL NOT NULL,
    payment_date TEXT NOT NULL,
    method      TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_case ON payments(case_id);
CREATE INDEX IF NOT EXISTS idx_payments_date ON payments(payment_date);

CREATE TABLE IF NOT EXISTS prescriptions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    rx_date     TEXT NOT NULL,
    rx_details  TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_prescriptions_case ON prescriptions(case_id);

CREATE TABLE IF NOT EXISTS login_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identifier  TEXT NOT NULL,
    purpose     TEXT NOT NULL,
    success     INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_attempts_lookup ON login_attempts(identifier, purpose, created_at);

CREATE TABLE IF NOT EXISTS case_consents (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id                 INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    consent_text            TEXT NOT NULL,
    signed_date             TEXT NOT NULL,
    signature_type          TEXT NOT NULL,
    signature_filename      TEXT,
    patient_name_at_signing TEXT,
    witness_name            TEXT,
    notes                   TEXT,
    created_at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_consents_case ON case_consents(case_id);

CREATE TABLE IF NOT EXISTS data_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id      INTEGER NOT NULL REFERENCES patients(id) ON DELETE CASCADE,
    request_type    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'Pending',
    description     TEXT NOT NULL DEFAULT '',
    resolution_note TEXT NOT NULL DEFAULT '',
    requested_at    TEXT NOT NULL,
    deadline_at     TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_data_requests_patient ON data_requests(patient_id);
CREATE INDEX IF NOT EXISTS idx_data_requests_status  ON data_requests(status);

CREATE TABLE IF NOT EXISTS case_amendments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    previous_cost   REAL NOT NULL,
    new_cost        REAL NOT NULL,
    reason          TEXT,
    amended_at      TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_amendments_case ON case_amendments(case_id);

CREATE TABLE IF NOT EXISTS case_visit_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id     INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    visit_date  TEXT NOT NULL,
    note        TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_case_visit_notes_case ON case_visit_notes(case_id);
"""

DEFAULT_SETTINGS = {
    "clinic_name": "Feast9",
    "clinic_address": "",
    "clinic_phone": "",
    "clinic_email": "",
}

# Distinct, accessible colors auto-assigned to doctors for the appointment
# calendar (kept away from the green/red/amber already used for
# status badges elsewhere, so the calendar reads clearly at a glance).
DOCTOR_COLOR_PALETTE = [
    "#1E88E5",  # blue
    "#8E24AA",  # purple
    "#EF6C00",  # orange
    "#00897B",  # teal
    "#D81B60",  # pink
    "#3949AB",  # indigo
    "#00ACC1",  # cyan
    "#6D4C41",  # brown
    "#455A64",  # slate
    "#5E35B1",  # deep purple
]
NO_DOCTOR_COLOR = "#9E9E9E"


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn, table: str, columns: dict):
    """Generic migration helper: adds any column in `columns` (name -> SQL
    type/default clause) that doesn't already exist on `table`. Safe to call
    on every boot — a no-op once the columns are present."""
    existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for col_name, col_def in columns.items():
        if col_name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")


def _migrate_doctor_colors(conn):
    """Adds the 'color' column to a pre-existing doctors table (from
    installs created before the Appointments feature) and backfills a
    distinct color for any doctor that doesn't have one yet."""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(doctors)").fetchall()]
    if "color" not in cols:
        # Default to '' (not a real color) so every pre-existing doctor gets
        # caught by the backfill below and assigned a distinct palette color,
        # rather than all sharing one default.
        conn.execute("ALTER TABLE doctors ADD COLUMN color TEXT NOT NULL DEFAULT ''")
    rows = conn.execute(
        "SELECT id FROM doctors WHERE color IS NULL OR color = '' ORDER BY id"
    ).fetchall()
    for i, r in enumerate(rows):
        color = DOCTOR_COLOR_PALETTE[i % len(DOCTOR_COLOR_PALETTE)]
        conn.execute("UPDATE doctors SET color=? WHERE id=?", (color, r["id"]))


def _migrate_users_security(conn):
    """Adds password-recovery columns to a pre-existing users table (from
    installs created before this feature existed)."""
    _ensure_columns(conn, "users", {
        "security_question": "TEXT NOT NULL DEFAULT ''",
        "security_answer_hash": "TEXT NOT NULL DEFAULT ''",
    })


def _migrate_patient_medical_fields(conn):
    """Adds medical-history/allergy/emergency-contact columns to a
    pre-existing patients table (from installs created before this feature
    existed). Existing patients simply start with these fields empty."""
    _ensure_columns(conn, "patients", {
        "medical_conditions_json": "TEXT NOT NULL DEFAULT '[]'",
        "medical_conditions_other": "TEXT NOT NULL DEFAULT ''",
        "is_pregnant": "INTEGER NOT NULL DEFAULT 0",
        "is_nursing": "INTEGER NOT NULL DEFAULT 0",
        "allergies_json": "TEXT NOT NULL DEFAULT '[]'",
        "allergies_other": "TEXT NOT NULL DEFAULT ''",
        "emergency_contact_name": "TEXT NOT NULL DEFAULT ''",
        "emergency_contact_relation": "TEXT NOT NULL DEFAULT ''",
        "emergency_contact_number": "TEXT NOT NULL DEFAULT ''",
    })


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate_doctor_colors(conn)
        _migrate_users_security(conn)
        _migrate_patient_medical_fields(conn)
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        existing = conn.execute("SELECT COUNT(*) c FROM procedure_types").fetchone()["c"]
        if existing == 0:
            for i, name in enumerate(DEFAULT_PROCEDURE_TYPES):
                conn.execute(
                    "INSERT INTO procedure_types (name, active, sort_order, created_at) "
                    "VALUES (?,1,?,?)",
                    (name, i, today_iso()),
                )


def has_any_user() -> bool:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] > 0


# ---------------------------------------------------------------------------
# Users / auth
# ---------------------------------------------------------------------------
def create_user(username: str, password_hash: str, security_question: str = "",
                 security_answer_hash: str = "") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO users (username, password_hash, security_question,
               security_answer_hash, created_at) VALUES (?,?,?,?,?)""",
            (username.strip(), password_hash, security_question, security_answer_hash,
             today_iso()),
        )
        return cur.lastrowid


def get_user_by_username(username: str):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username=?", (username.strip(),)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None


def update_user_password(user_id: int, password_hash: str):
    with get_conn() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, user_id))


def update_security_question(user_id: int, question: str, answer_hash: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET security_question=?, security_answer_hash=? WHERE id=?",
            (question, answer_hash, user_id),
        )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def get_all_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def set_setting(key: str, value: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


# ---------------------------------------------------------------------------
# Doctors
# ---------------------------------------------------------------------------
def add_doctor(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Doctor name is required.")
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) c FROM doctors").fetchone()["c"]
        color = DOCTOR_COLOR_PALETTE[count % len(DOCTOR_COLOR_PALETTE)]
        cur = conn.execute(
            "INSERT INTO doctors (name, active, color, created_at) VALUES (?, 1, ?, ?)",
            (name, color, today_iso()),
        )
        return cur.lastrowid


def list_doctors(active_only: bool = False) -> list:
    with get_conn() as conn:
        q = "SELECT * FROM doctors"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def get_doctor(doctor_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM doctors WHERE id=?", (doctor_id,)).fetchone()
        return dict(row) if row else None


def update_doctor(doctor_id: int, name: str, color: str = None):
    with get_conn() as conn:
        if color:
            conn.execute("UPDATE doctors SET name=?, color=? WHERE id=?",
                         (name.strip(), color, doctor_id))
        else:
            conn.execute("UPDATE doctors SET name=? WHERE id=?", (name.strip(), doctor_id))


def doctor_color(doctor_id) -> str:
    if not doctor_id:
        return NO_DOCTOR_COLOR
    with get_conn() as conn:
        row = conn.execute("SELECT color FROM doctors WHERE id=?", (doctor_id,)).fetchone()
        return row["color"] if row and row["color"] else NO_DOCTOR_COLOR


def set_doctor_active(doctor_id: int, active: bool):
    with get_conn() as conn:
        conn.execute("UPDATE doctors SET active=? WHERE id=?", (1 if active else 0, doctor_id))


def doctor_in_use(doctor_id: int) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM cases WHERE doctor_id=?", (doctor_id,)
        ).fetchone()
        return row["c"] > 0


# ---------------------------------------------------------------------------
# Procedure types (the "manage case types" screen)
# ---------------------------------------------------------------------------
def add_procedure_type(name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Procedure name is required.")
    with get_conn() as conn:
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order),0) m FROM procedure_types"
        ).fetchone()["m"]
        cur = conn.execute(
            "INSERT INTO procedure_types (name, active, sort_order, created_at) "
            "VALUES (?,1,?,?)",
            (name, max_order + 1, today_iso()),
        )
        return cur.lastrowid


def list_procedure_types(active_only: bool = False) -> list:
    with get_conn() as conn:
        q = "SELECT * FROM procedure_types"
        if active_only:
            q += " WHERE active=1"
        q += " ORDER BY sort_order, name"
        return [dict(r) for r in conn.execute(q).fetchall()]


def update_procedure_type(pt_id: int, name: str):
    with get_conn() as conn:
        conn.execute("UPDATE procedure_types SET name=? WHERE id=?", (name.strip(), pt_id))


def set_procedure_type_active(pt_id: int, active: bool):
    with get_conn() as conn:
        conn.execute(
            "UPDATE procedure_types SET active=? WHERE id=?", (1 if active else 0, pt_id)
        )


def delete_procedure_type(pt_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM procedure_types WHERE id=?", (pt_id,))


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
def add_patient(name, age, sex, mobile, email, address, last_visited_date,
                 is_historic_import=0, medical_conditions=None, medical_conditions_other="",
                 is_pregnant=0, is_nursing=0, allergies=None, allergies_other="",
                 emergency_contact_name="", emergency_contact_relation="",
                 emergency_contact_number="", dpdp_notice_accepted=0,
                 dpdp_notice_accepted_at="", comms_consent=0, comms_consent_at="",
                 guardian_name="", guardian_relation="", guardian_mobile="") -> int:
    now = today_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO patients
               (name, age, sex, mobile, email, address, last_visited_date,
                created_at, updated_at, is_historic_import,
                medical_conditions_json, medical_conditions_other,
                is_pregnant, is_nursing, allergies_json, allergies_other,
                emergency_contact_name, emergency_contact_relation, emergency_contact_number,
                dpdp_notice_accepted, dpdp_notice_accepted_at,
                comms_consent, comms_consent_at,
                guardian_name, guardian_relation, guardian_mobile)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (name.strip(), age or None, sex, mobile.strip(), email or "", address or "",
             last_visited_date or "", now, now, is_historic_import,
             json.dumps(medical_conditions or []), medical_conditions_other or "",
             1 if is_pregnant else 0, 1 if is_nursing else 0,
             json.dumps(allergies or []), allergies_other or "",
             emergency_contact_name or "", emergency_contact_relation or "",
             emergency_contact_number or "",
             1 if dpdp_notice_accepted else 0, dpdp_notice_accepted_at or "",
             1 if comms_consent else 0, comms_consent_at or "",
             guardian_name or "", guardian_relation or "", guardian_mobile or ""),
        )
        return cur.lastrowid


def update_patient(patient_id, name, age, sex, mobile, email, address, last_visited_date,
                    medical_conditions=None, medical_conditions_other="",
                    is_pregnant=0, is_nursing=0, allergies=None, allergies_other="",
                    emergency_contact_name="", emergency_contact_relation="",
                    emergency_contact_number="", dpdp_notice_accepted=None,
                    dpdp_notice_accepted_at=None, comms_consent=None, comms_consent_at=None,
                    guardian_name="", guardian_relation="", guardian_mobile=""):
    with get_conn() as conn:
        ex = conn.execute(
            "SELECT dpdp_notice_accepted, dpdp_notice_accepted_at, comms_consent, comms_consent_at "
            "FROM patients WHERE id=?", (patient_id,)
        ).fetchone()
        ex = dict(ex) if ex else {}
        dna    = (1 if dpdp_notice_accepted else 0) if dpdp_notice_accepted is not None else ex.get("dpdp_notice_accepted", 0)
        dna_at = dpdp_notice_accepted_at if dpdp_notice_accepted_at is not None else ex.get("dpdp_notice_accepted_at", "")
        cc     = (1 if comms_consent else 0) if comms_consent is not None else ex.get("comms_consent", 0)
        cc_at  = comms_consent_at if comms_consent_at is not None else ex.get("comms_consent_at", "")
        conn.execute(
            """UPDATE patients SET name=?, age=?, sex=?, mobile=?, email=?, address=?,
               last_visited_date=?, updated_at=?,
               medical_conditions_json=?, medical_conditions_other=?,
               is_pregnant=?, is_nursing=?, allergies_json=?, allergies_other=?,
               emergency_contact_name=?, emergency_contact_relation=?,
               emergency_contact_number=?,
               dpdp_notice_accepted=?, dpdp_notice_accepted_at=?,
               comms_consent=?, comms_consent_at=?,
               guardian_name=?, guardian_relation=?, guardian_mobile=?
               WHERE id=?""",
            (name.strip(), age or None, sex, mobile.strip(), email or "", address or "",
             last_visited_date or "", today_iso(),
             json.dumps(medical_conditions or []), medical_conditions_other or "",
             1 if is_pregnant else 0, 1 if is_nursing else 0,
             json.dumps(allergies or []), allergies_other or "",
             emergency_contact_name or "", emergency_contact_relation or "",
             emergency_contact_number or "",
             dna, dna_at, cc, cc_at,
             guardian_name or "", guardian_relation or "", guardian_mobile or "",
             patient_id),
        )


def update_comms_consent(patient_id: int, consent: bool):
    """Standalone update for communication consent preference."""
    from app.validators import now_iso
    with get_conn() as conn:
        conn.execute(
            "UPDATE patients SET comms_consent=?, comms_consent_at=?, updated_at=? WHERE id=?",
            (1 if consent else 0, now_iso(), today_iso(), patient_id),
        )


def update_case_followup(case_id: int, follow_up_date: str, next_action_note: str):
    """Quick update of follow-up date and next action note without touching
    other case fields — called from the inline follow-up form on case detail."""
    with get_conn() as conn:
        conn.execute(
            "UPDATE cases SET follow_up_date=?, next_action_note=?, updated_at=? WHERE id=?",
            (follow_up_date or "", next_action_note or "", today_iso(), case_id),
        )


def touch_last_visited(patient_id, visit_date=None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE patients SET last_visited_date=?, updated_at=? WHERE id=?",
            (visit_date or today_iso(), today_iso(), patient_id),
        )


def get_patient(patient_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM patients WHERE id=?", (patient_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["medical_conditions"] = json.loads(d.get("medical_conditions_json") or "[]")
        d["allergies"] = json.loads(d.get("allergies_json") or "[]")
        d["has_medical_alerts"] = bool(
            d["medical_conditions"] or d.get("medical_conditions_other") or
            d["allergies"] or d.get("allergies_other") or d.get("is_pregnant") or
            d.get("is_nursing")
        )
        d["is_minor"] = bool(d.get("age") and int(d["age"]) < 18)
        d["needs_guardian"] = d["is_minor"] and not d.get("guardian_name")
        return d


def delete_patient(patient_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM patients WHERE id=?", (patient_id,))


def list_patients(search: str = "", page: int = 1, page_size: int = 50) -> dict:
    offset = max(page - 1, 0) * page_size
    with get_conn() as conn:
        if search:
            like = f"%{search.strip()}%"
            total = conn.execute(
                "SELECT COUNT(*) c FROM patients WHERE name LIKE ? OR mobile LIKE ? OR email LIKE ?",
                (like, like, like),
            ).fetchone()["c"]
            rows = conn.execute(
                """SELECT * FROM patients
                   WHERE name LIKE ? OR mobile LIKE ? OR email LIKE ?
                   ORDER BY name LIMIT ? OFFSET ?""",
                (like, like, like, page_size, offset),
            ).fetchall()
        else:
            total = conn.execute("SELECT COUNT(*) c FROM patients").fetchone()["c"]
            rows = conn.execute(
                "SELECT * FROM patients ORDER BY name LIMIT ? OFFSET ?", (page_size, offset)
            ).fetchall()
    def _flag(r):
        d = dict(r)
        conditions = json.loads(d.get("medical_conditions_json") or "[]")
        allergies = json.loads(d.get("allergies_json") or "[]")
        d["has_medical_alert"] = bool(
            conditions or d.get("medical_conditions_other") or allergies or
            d.get("allergies_other") or d.get("is_pregnant") or d.get("is_nursing")
        )
        return d

    return {
        "patients": [_flag(r) for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


def patient_active_case_count(patient_id) -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM cases WHERE patient_id=? AND status='Active'", (patient_id,)
        ).fetchone()["c"]


def patient_outstanding_balance(patient_id) -> float:
    with get_conn() as conn:
        cases = conn.execute(
            "SELECT id, total_cost FROM cases WHERE patient_id=? AND status='Active'",
            (patient_id,),
        ).fetchall()
        total = 0.0
        for c in cases:
            paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE case_id=?", (c["id"],)
            ).fetchone()["s"]
            total += c["total_cost"] - paid
    return round(total, 2)


def count_patients() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM patients").fetchone()["c"]


def bulk_add_patients(rows: list) -> int:
    """Fast path for the historic-data importer: inserts many patients in a
    single transaction instead of one connection per row. `rows` is a list
    of dicts with keys name/age/sex/mobile/email/address/last_visited_date,
    and optionally medical_conditions_other/allergies_other/
    emergency_contact_name/emergency_contact_number if the source
    spreadsheet happened to have free-text columns for those."""
    now = today_iso()
    payload = [
        (r["name"].strip(), r.get("age") or None, r.get("sex") or "",
         r["mobile"].strip(), r.get("email") or "", r.get("address") or "",
         r.get("last_visited_date") or "", now, now, 1,
         r.get("medical_conditions_other") or "", r.get("allergies_other") or "",
         r.get("emergency_contact_name") or "", r.get("emergency_contact_number") or "")
        for r in rows
    ]
    with get_conn() as conn:
        conn.executemany(
            """INSERT INTO patients
               (name, age, sex, mobile, email, address, last_visited_date,
                created_at, updated_at, is_historic_import,
                medical_conditions_other, allergies_other,
                emergency_contact_name, emergency_contact_number)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            payload,
        )
    return len(payload)


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
def add_case(patient_id, title, status, procedures, custom_procedure, doctor_id,
             total_cost, next_action_note, follow_up_date) -> int:
    now = today_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO cases
               (patient_id, title, status, procedures_json, custom_procedure, doctor_id,
                total_cost, next_action_note, follow_up_date, created_at, updated_at,
                closed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (patient_id, title.strip(), status, json.dumps(procedures or []),
             custom_procedure or "", doctor_id, float(total_cost or 0),
             next_action_note or "", follow_up_date or "", now, now,
             now if status == "Closed" else None),
        )
        case_id = cur.lastrowid
    touch_last_visited(patient_id)
    return case_id


def update_case(case_id, title, status, procedures, custom_procedure, doctor_id,
                 total_cost, next_action_note, follow_up_date):
    existing = get_case(case_id)
    closed_at = existing["closed_at"]
    if status == "Closed" and existing["status"] != "Closed":
        closed_at = now_iso()   # second-precision timestamp: set only when doctor explicitly closes
    elif status != "Closed" and existing["status"] == "Closed":
        closed_at = None        # case re-opened: clear the closure timestamp
    elif status == "Active":
        closed_at = None
    with get_conn() as conn:
        conn.execute(
            """UPDATE cases SET title=?, status=?, procedures_json=?, custom_procedure=?,
               doctor_id=?, total_cost=?, next_action_note=?, follow_up_date=?,
               updated_at=?, closed_at=? WHERE id=?""",
            (title.strip(), status, json.dumps(procedures or []), custom_procedure or "",
             doctor_id, float(total_cost or 0), next_action_note or "",
             follow_up_date or "", today_iso(), closed_at, case_id),
        )


def get_case(case_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["procedures"] = json.loads(d.get("procedures_json") or "[]")
        return d


def delete_case(case_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM cases WHERE id=?", (case_id,))


def list_cases_for_patient(patient_id) -> list:
    """Active cases first (most recently updated first), then closed cases."""
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM cases WHERE patient_id=?
               ORDER BY (status='Closed'), updated_at DESC""",
            (patient_id,),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["procedures"] = json.loads(d.get("procedures_json") or "[]")
        d["balance"] = get_case_balance(d["id"])
        d["paid"] = get_case_total_paid(d["id"])
        out.append(d)
    return out


def list_all_cases(status: str = None, doctor_id: int = None) -> list:
    with get_conn() as conn:
        q = ("SELECT c.*, p.name as patient_name, p.mobile as patient_mobile FROM cases c "
             "JOIN patients p ON p.id = c.patient_id WHERE 1=1")
        params = []
        if status:
            q += " AND c.status=?"
            params.append(status)
        if doctor_id:
            q += " AND c.doctor_id=?"
            params.append(doctor_id)
        q += " ORDER BY (c.status='Closed'), c.updated_at DESC"
        rows = conn.execute(q, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["balance"] = get_case_balance(d["id"])
            out.append(d)
        return out


def case_doctor_name(case: dict) -> str:
    if not case.get("doctor_id"):
        return "—"
    with get_conn() as conn:
        row = conn.execute("SELECT name FROM doctors WHERE id=?", (case["doctor_id"],)).fetchone()
        return row["name"] if row else "—"


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------
def add_payment(case_id, amount, payment_date, method="", note="") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO payments (case_id, amount, payment_date, method, note, created_at)
               VALUES (?,?,?,?,?,?)""",
            (case_id, float(amount), payment_date or today_iso(), method, note, today_iso()),
        )
        new_id = cur.lastrowid
        case = conn.execute("SELECT patient_id FROM cases WHERE id=?", (case_id,)).fetchone()
    if case:
        touch_last_visited(case["patient_id"], payment_date or today_iso())
    return new_id


def get_payment(payment_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        return dict(row) if row else None


def delete_payment(payment_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM payments WHERE id=?", (payment_id,))


def list_payments_for_case(case_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM payments WHERE case_id=? ORDER BY payment_date, id", (case_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_case_balance(case_id) -> float:
    with get_conn() as conn:
        case = conn.execute("SELECT total_cost FROM cases WHERE id=?", (case_id,)).fetchone()
        if not case:
            return 0.0
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE case_id=?", (case_id,)
        ).fetchone()["s"]
        return round(case["total_cost"] - paid, 2)


def get_case_total_paid(case_id) -> float:
    with get_conn() as conn:
        paid = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE case_id=?", (case_id,)
        ).fetchone()["s"]
        return round(paid, 2)


# ---------------------------------------------------------------------------
# Prescriptions
# ---------------------------------------------------------------------------
def add_prescription(case_id, rx_date, rx_details) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO prescriptions (case_id, rx_date, rx_details, created_at) VALUES (?,?,?,?)",
            (case_id, rx_date or today_iso(), rx_details, today_iso()),
        )
        return cur.lastrowid


def get_prescription(prescription_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM prescriptions WHERE id=?", (prescription_id,)
        ).fetchone()
        return dict(row) if row else None


def list_prescriptions_for_case(case_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM prescriptions WHERE case_id=? ORDER BY rx_date DESC, id DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_prescription(prescription_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM prescriptions WHERE id=?", (prescription_id,))


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------
def get_followup_alerts():
    from datetime import date, timedelta
    today = date.today().isoformat()
    in_3  = (date.today() + timedelta(days=3)).isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.id as case_id, c.title, c.follow_up_date, c.next_action_note,
                      p.id as patient_id, p.name as patient_name, p.mobile
               FROM cases c JOIN patients p ON p.id = c.patient_id
               WHERE c.status='Active' AND c.follow_up_date IS NOT NULL
                     AND c.follow_up_date != ''
               ORDER BY c.follow_up_date"""
        ).fetchall()
    overdue, upcoming = [], []
    for r in rows:
        d = dict(r)
        if d["follow_up_date"] < today:
            overdue.append(d)
        elif d["follow_up_date"] <= in_3:
            upcoming.append(d)
    return overdue, upcoming


def get_total_outstanding() -> float:
    """Sum of (total_cost - paid) across all Active cases — balance stays
    visible/counted only while a case remains open, per spec."""
    with get_conn() as conn:
        cases = conn.execute("SELECT id, total_cost FROM cases WHERE status='Active'").fetchall()
        total = 0.0
        for c in cases:
            paid = conn.execute(
                "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE case_id=?", (c["id"],)
            ).fetchone()["s"]
            total += c["total_cost"] - paid
    return round(total, 2)


def get_active_case_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM cases WHERE status='Active'").fetchone()["c"]


def get_closed_case_count() -> int:
    with get_conn() as conn:
        return conn.execute("SELECT COUNT(*) c FROM cases WHERE status='Closed'").fetchone()["c"]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def get_revenue_collected(start_date: str, end_date: str) -> float:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments WHERE payment_date BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()
        return round(row["s"], 2)


def get_cases_closed_count(start_date: str, end_date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM cases WHERE status='Closed' AND closed_at BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()
        return row["c"]


def get_new_cases_count(start_date: str, end_date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM cases WHERE created_at BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()
        return row["c"]


def get_new_patients_count(start_date: str, end_date: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM patients WHERE created_at BETWEEN ? AND ?",
            (start_date, end_date),
        ).fetchone()
        return row["c"]


def get_payments_in_range(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT pay.*, c.title as case_title, p.name as patient_name
               FROM payments pay
               JOIN cases c ON c.id = pay.case_id
               JOIN patients p ON p.id = c.patient_id
               WHERE pay.payment_date BETWEEN ? AND ?
               ORDER BY pay.payment_date""",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]


def get_cases_closed_in_range(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.*, p.name as patient_name FROM cases c
               JOIN patients p ON p.id = c.patient_id
               WHERE c.status='Closed' AND c.closed_at BETWEEN ? AND ?
               ORDER BY c.closed_at""",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]


def get_monthly_revenue_series(year: int) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT strftime('%m', payment_date) as m, COALESCE(SUM(amount),0) s
               FROM payments WHERE strftime('%Y', payment_date) = ?
               GROUP BY m""",
            (str(year),),
        ).fetchall()
    by_month = {r["m"]: r["s"] for r in rows}
    return [round(by_month.get(f"{i:02d}", 0.0), 2) for i in range(1, 13)]


def get_revenue_summary() -> dict:
    """All-time and current-state revenue/pending summary — used for the
    'Total Revenue vs Pending' section of the reports page."""
    with get_conn() as conn:
        # Total billed across ALL cases ever created
        total_billed = conn.execute(
            "SELECT COALESCE(SUM(total_cost),0) s FROM cases"
        ).fetchone()["s"]

        # Total collected (all payments ever received)
        total_collected = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments"
        ).fetchone()["s"]

        # Outstanding on Active cases (amount billed but not yet paid)
        active_cases = conn.execute(
            "SELECT id, total_cost FROM cases WHERE status='Active'"
        ).fetchall()
        active_billed = sum(c["total_cost"] for c in active_cases)
        active_paid_map = {}
        if active_cases:
            ids = ",".join("?" * len(active_cases))
            for r in conn.execute(
                f"SELECT case_id, COALESCE(SUM(amount),0) s FROM payments "
                f"WHERE case_id IN ({ids}) GROUP BY case_id",
                [c["id"] for c in active_cases]
            ).fetchall():
                active_paid_map[r["case_id"]] = r["s"]
        active_paid = sum(active_paid_map.get(c["id"], 0) for c in active_cases)
        pending_active = round(max(active_billed - active_paid, 0), 2)

        # Cases with overdue follow-up that still have an outstanding balance
        today = today_iso()
        overdue_outstanding = conn.execute(
            """SELECT COUNT(*) c FROM cases c2
               WHERE c2.status='Active' AND c2.follow_up_date != ''
               AND c2.follow_up_date < ?
               AND c2.id IN (
                   SELECT case_id FROM (
                       SELECT p2.case_id,
                              c3.total_cost - COALESCE(SUM(p2.amount),0) AS bal
                       FROM cases c3
                       LEFT JOIN payments p2 ON p2.case_id = c3.id
                       WHERE c3.status='Active'
                       GROUP BY p2.case_id, c3.id
                   ) WHERE bal > 0
               )""", (today,)
        ).fetchone()["c"]

        # Patient+case level pending payment view — all cases with outstanding balances,
        # sorted by pending amount descending so the largest debtors appear first.
        patient_case_pending = conn.execute(
            """SELECT p.name as patient_name, p.mobile, p.id as patient_id,
                      c.id as case_id, c.title as case_title, c.status,
                      c.total_cost,
                      COALESCE(SUM(pay.amount), 0) as paid,
                      c.total_cost - COALESCE(SUM(pay.amount), 0) as pending,
                      c.follow_up_date,
                      d.name as doctor_name
               FROM cases c
               JOIN patients p ON p.id = c.patient_id
               LEFT JOIN payments pay ON pay.case_id = c.id
               LEFT JOIN doctors d ON d.id = c.doctor_id
               GROUP BY c.id
               HAVING pending > 0.005
               ORDER BY pending DESC"""
        ).fetchall()

    return {
        "total_billed":        round(total_billed, 2),
        "total_collected":     round(total_collected, 2),
        "total_pending":       round(max(total_billed - total_collected, 0), 2),
        "collection_rate":     round((total_collected / total_billed * 100) if total_billed else 0, 1),
        "pending_active":      pending_active,
        "active_case_count":   len(active_cases),
        "overdue_outstanding": overdue_outstanding,
        "patient_case_pending": [dict(r) for r in patient_case_pending],
    }


# ---------------------------------------------------------------------------
# Appointments
# ---------------------------------------------------------------------------
APPOINTMENT_STATUSES = ["Scheduled", "Completed", "Cancelled", "No-show"]

_APPT_SELECT = """
    SELECT a.*, p.name as patient_name, p.mobile as patient_mobile,
           d.name as doctor_name, d.color as doctor_color, c.title as case_title
    FROM appointments a
    JOIN patients p ON p.id = a.patient_id
    LEFT JOIN doctors d ON d.id = a.doctor_id
    LEFT JOIN cases c ON c.id = a.case_id
"""


def add_appointment(patient_id, doctor_id, appt_date, start_time, end_time,
                     title, notes, status="Scheduled", case_id=None) -> int:
    now = today_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO appointments
               (patient_id, case_id, doctor_id, appt_date, start_time, end_time,
                title, notes, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (patient_id, case_id or None, doctor_id or None, appt_date, start_time,
             end_time or None, title or "", notes or "", status, now, now),
        )
        return cur.lastrowid


def update_appointment(appt_id, patient_id, doctor_id, appt_date, start_time, end_time,
                        title, notes, status, case_id=None):
    with get_conn() as conn:
        conn.execute(
            """UPDATE appointments SET patient_id=?, case_id=?, doctor_id=?, appt_date=?,
               start_time=?, end_time=?, title=?, notes=?, status=?, updated_at=?
               WHERE id=?""",
            (patient_id, case_id or None, doctor_id or None, appt_date, start_time,
             end_time or None, title or "", notes or "", status, today_iso(), appt_id),
        )


def get_appointment(appt_id):
    with get_conn() as conn:
        row = conn.execute(_APPT_SELECT + " WHERE a.id=?", (appt_id,)).fetchone()
        return dict(row) if row else None


def delete_appointment(appt_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM appointments WHERE id=?", (appt_id,))


def set_appointment_status(appt_id, status):
    with get_conn() as conn:
        conn.execute("UPDATE appointments SET status=?, updated_at=? WHERE id=?",
                     (status, today_iso(), appt_id))


def list_appointments_for_range(start_date: str, end_date: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            _APPT_SELECT + " WHERE a.appt_date BETWEEN ? AND ? "
            "ORDER BY a.appt_date, a.start_time",
            (start_date, end_date),
        ).fetchall()
        return [dict(r) for r in rows]


def list_appointments_for_day(day: str) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            _APPT_SELECT + " WHERE a.appt_date=? ORDER BY a.start_time", (day,)
        ).fetchall()
        return [dict(r) for r in rows]


def list_appointments_for_patient(patient_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            _APPT_SELECT + " WHERE a.patient_id=? ORDER BY a.appt_date DESC, a.start_time DESC",
            (patient_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_todays_appointments() -> list:
    return list_appointments_for_day(today_iso())


def get_patients_followup_status(patient_ids: list) -> dict:
    if not patient_ids:
        return {}
    from datetime import date, timedelta
    today = date.today().isoformat()
    soon  = (date.today() + timedelta(days=3)).isoformat()
    ids   = ",".join("?" * len(patient_ids))
    with get_conn() as conn:
        rows = conn.execute(
            f"""SELECT patient_id, MIN(follow_up_date) as earliest
                FROM cases WHERE patient_id IN ({ids})
                AND status='Active' AND follow_up_date!='' AND follow_up_date IS NOT NULL
                GROUP BY patient_id""", patient_ids).fetchall()
    result = {}
    for r in rows:
        if r["earliest"] < today:   result[r["patient_id"]] = "overdue"
        elif r["earliest"] <= soon: result[r["patient_id"]] = "upcoming"
    return result


def search_patients_basic(query: str, limit: int = 10) -> list:
    """Lightweight patient search used by the appointment form's autocomplete."""
    like = f"%{query.strip()}%"
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT id, name, mobile FROM patients
               WHERE name LIKE ? OR mobile LIKE ?
               ORDER BY name LIMIT ?""",
            (like, like, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Rate limiting — DB-backed (not in-memory) so it works correctly even with
# multiple gunicorn worker processes, and survives a restart.
# ---------------------------------------------------------------------------
RATE_LIMIT_WINDOW_MINUTES = 15
RATE_LIMIT_MAX_ATTEMPTS = 8


def record_login_attempt(identifier: str, purpose: str, success: bool):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO login_attempts (identifier, purpose, success, created_at) "
            "VALUES (?,?,?,?)",
            (identifier, purpose, 1 if success else 0, now_iso()),
        )


def is_rate_limited(identifier: str, purpose: str) -> bool:
    """True if `identifier` (e.g. an IP address) has racked up too many
    failed attempts for `purpose` (e.g. 'login') recently. Successful
    attempts don't count against the limit."""
    cutoff = (datetime.now() - timedelta(minutes=RATE_LIMIT_WINDOW_MINUTES)).strftime(
        "%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        row = conn.execute(
            """SELECT COUNT(*) c FROM login_attempts
               WHERE identifier=? AND purpose=? AND success=0 AND created_at >= ?""",
            (identifier, purpose, cutoff),
        ).fetchone()
        return row["c"] >= RATE_LIMIT_MAX_ATTEMPTS


def prune_old_login_attempts(days: int = 7):
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    with get_conn() as conn:
        conn.execute("DELETE FROM login_attempts WHERE created_at < ?", (cutoff,))


# ---------------------------------------------------------------------------
# Case consents — signed (or print-and-scan) consent forms per case. A case
# can have more than one over time, e.g. a fresh consent when the
# treatment plan changes materially mid-case.
# ---------------------------------------------------------------------------
SIGNATURE_TYPE_DRAWN = "drawn"
SIGNATURE_TYPE_UPLOADED = "uploaded"
SIGNATURE_TYPE_NONE = "none"  # blank form printed for an on-paper-only record


def add_consent(case_id, consent_text, signed_date, signature_type, signature_filename,
                 patient_name_at_signing, witness_name="", notes="") -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO case_consents
               (case_id, consent_text, signed_date, signature_type, signature_filename,
                patient_name_at_signing, witness_name, notes, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (case_id, consent_text, signed_date, signature_type, signature_filename,
             patient_name_at_signing, witness_name or "", notes or "", today_iso()),
        )
        return cur.lastrowid


def get_consent(consent_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM case_consents WHERE id=?", (consent_id,)).fetchone()
        return dict(row) if row else None


def list_consents_for_case(case_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM case_consents WHERE case_id=? ORDER BY signed_date DESC, id DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_consent(consent_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM case_consents WHERE id=?", (consent_id,))


def case_has_consent(case_id) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) c FROM case_consents WHERE case_id=?", (case_id,)
        ).fetchone()
        return row["c"] > 0


# ---------------------------------------------------------------------------
# Case cost amendments — tracked history of estimate revisions mid-treatment
# (e.g. "after 2 sittings we identified the need for surgery, estimate
# increased from 5,000 to 15,000"). Every change to a case's total_cost
# after its initial creation should go through revise_case_cost() so there's
# a dated, reasoned record instead of a silent overwrite.
# ---------------------------------------------------------------------------
def revise_case_cost(case_id, new_cost, reason, amended_at=None):
    """Updates the case's total_cost and logs the change. No-ops (returns
    None) if new_cost is the same as the current cost. Returns the new
    amendment's id otherwise."""
    case = get_case(case_id)
    if not case:
        raise ValueError("Case not found.")
    previous_cost = case["total_cost"]
    new_cost = round(float(new_cost), 2)
    if abs(new_cost - previous_cost) < 0.005:
        return None
    now = today_iso()
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO case_amendments
               (case_id, previous_cost, new_cost, reason, amended_at, created_at)
               VALUES (?,?,?,?,?,?)""",
            (case_id, previous_cost, new_cost, reason or "", amended_at or now, now),
        )
        conn.execute(
            "UPDATE cases SET total_cost=?, updated_at=? WHERE id=?",
            (new_cost, now, case_id),
        )
        return cur.lastrowid


def list_case_amendments(case_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM case_amendments WHERE case_id=? ORDER BY amended_at DESC, id DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_case_amendment(amendment_id):
    """Removes a logged amendment entry only — does not change the case's
    current total_cost (use revise_case_cost again if you need to correct
    the value itself). Mainly for fixing a mis-logged reason/typo entry."""
    with get_conn() as conn:
        conn.execute("DELETE FROM case_amendments WHERE id=?", (amendment_id,))


# ---------------------------------------------------------------------------
# Case visit notes — a running log so the case can be updated at each
# subsequent visit (what was done/observed today) without overwriting any
# single field, similar in spirit to the payment and prescription logs.
# ---------------------------------------------------------------------------
def add_visit_note(case_id, visit_date, note) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO case_visit_notes (case_id, visit_date, note, created_at) VALUES (?,?,?,?)",
            (case_id, visit_date or today_iso(), note, today_iso()),
        )
        case = conn.execute("SELECT patient_id FROM cases WHERE id=?", (case_id,)).fetchone()
    if case:
        touch_last_visited(case["patient_id"], visit_date or today_iso())
    return cur.lastrowid


def list_visit_notes(case_id) -> list:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM case_visit_notes WHERE case_id=? ORDER BY visit_date DESC, id DESC",
            (case_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_visit_note(note_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM case_visit_notes WHERE id=?", (note_id,))


# ---------------------------------------------------------------------------
# DPDP Phase 2 — Data Principal Rights
# Request types match the four statutory rights in the DPDP Act 2023.
# ---------------------------------------------------------------------------
DATA_REQUEST_TYPES = [
    "Access",            # Section 11 — right to know what is held
    "Correction",        # Section 12 — right to correct inaccurate data
    "Erasure",           # Section 13 — right to have data erased
    "Withdraw Consent",  # Section 6(6) — right to withdraw consent
]
DATA_REQUEST_STATUSES = ["Pending", "In Progress", "Completed", "Rejected"]
DATA_REQUEST_DEADLINE_DAYS = 90   # Section 13 + Rule timelines


def add_data_request(patient_id: int, request_type: str, description: str = "") -> int:
    from datetime import datetime, timedelta
    now_str  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deadline = (datetime.now() + timedelta(days=DATA_REQUEST_DEADLINE_DAYS)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO data_requests
               (patient_id, request_type, status, description, resolution_note,
                requested_at, deadline_at, resolved_at, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (patient_id, request_type, "Pending", description or "",
             "", now_str, deadline, "", today_iso()),
        )
        return cur.lastrowid


def get_data_request(request_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM data_requests WHERE id=?", (request_id,)).fetchone()
        return dict(row) if row else None


def list_data_requests(patient_id: int = None, status: str = None) -> list:
    with get_conn() as conn:
        q = """SELECT dr.*, p.name as patient_name, p.mobile as patient_mobile
               FROM data_requests dr JOIN patients p ON p.id = dr.patient_id
               WHERE 1=1"""
        params = []
        if patient_id:
            q += " AND dr.patient_id=?"
            params.append(patient_id)
        if status:
            q += " AND dr.status=?"
            params.append(status)
        q += " ORDER BY dr.requested_at DESC"
        return [dict(r) for r in conn.execute(q, params).fetchall()]


def update_data_request(request_id: int, status: str, resolution_note: str = ""):
    resolved_at = today_iso() if status in ("Completed", "Rejected") else ""
    with get_conn() as conn:
        conn.execute(
            """UPDATE data_requests SET status=?, resolution_note=?, resolved_at=?
               WHERE id=?""",
            (status, resolution_note or "", resolved_at, request_id),
        )


def count_pending_data_requests() -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) c FROM data_requests WHERE status='Pending'"
        ).fetchone()["c"]


def anonymise_patient(patient_id: int) -> bool:
    """Soft-erasure: blanks all personally identifying fields while keeping
    the clinical and financial records the law requires us to retain.
    The patient record itself is marked as anonymised and is not deleted.
    Returns True on success, False if patient not found."""
    patient = get_patient(patient_id)
    if not patient:
        return False
    with get_conn() as conn:
        conn.execute(
            """UPDATE patients SET
               name='[Anonymised]', mobile='0000000000', email='',
               address='', emergency_contact_name='', emergency_contact_number='',
               emergency_contact_relation='', guardian_name='', guardian_mobile='',
               guardian_relation='', medical_conditions_json='[]',
               medical_conditions_other='', allergies_json='[]', allergies_other='',
               is_pregnant=0, is_nursing=0,
               comms_consent=0, comms_consent_at='',
               updated_at=?
               WHERE id=?""",
            (today_iso(), patient_id),
        )
    return True


# ---------------------------------------------------------------------------
# Analytics module DB queries
# ---------------------------------------------------------------------------

def get_analytics_data(year: int = None) -> dict:
    """All analytics queries in a single connection — called once per
    page load for the Analytics tab (business insights / future planning)."""
    from datetime import date as dt_date
    import json as _json
    if not year:
        year = dt_date.today().year
    yr = str(year)

    with get_conn() as conn:

        # ── 1. Monthly footfalls + revenue + appointments ────────────────
        monthly_patients = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',created_at) m, COUNT(*) c FROM patients "
                "WHERE strftime('%Y',created_at)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        monthly_revenue = {
            r["m"]: r["s"] for r in conn.execute(
                "SELECT strftime('%m',payment_date) m, COALESCE(SUM(amount),0) s "
                "FROM payments WHERE strftime('%Y',payment_date)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        monthly_cases = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',created_at) m, COUNT(*) c FROM cases "
                "WHERE strftime('%Y',created_at)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        monthly_appointments = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',appt_date) m, COUNT(*) c FROM appointments "
                "WHERE strftime('%Y',appt_date)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun",
                        "Jul","Aug","Sep","Oct","Nov","Dec"]
        monthly_trend = [
            {
                "month":        month_labels[i],
                "patients":     monthly_patients.get(f"{i+1:02d}", 0),
                "revenue":      round(monthly_revenue.get(f"{i+1:02d}", 0), 2),
                "cases":        monthly_cases.get(f"{i+1:02d}", 0),
                "appointments": monthly_appointments.get(f"{i+1:02d}", 0),
            }
            for i in range(12)
        ]

        # ── 2. Day-of-week trends (appointments + revenue) ───────────────
        day_labels = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
        dow_appts = {
            r["d"]: r["c"] for r in conn.execute(
                "SELECT strftime('%w',appt_date) d, COUNT(*) c FROM appointments "
                "WHERE strftime('%Y',appt_date)=? GROUP BY d", (yr,)
            ).fetchall()
        }
        dow_payments = {
            r["d"]: r["s"] for r in conn.execute(
                "SELECT strftime('%w',payment_date) d, COALESCE(SUM(amount),0) s "
                "FROM payments WHERE strftime('%Y',payment_date)=? GROUP BY d", (yr,)
            ).fetchall()
        }
        dow_trend = [
            {
                "day":     day_labels[i],
                "appts":   dow_appts.get(str(i), 0),
                "revenue": round(dow_payments.get(str(i), 0), 2),
            }
            for i in range(7)
        ]

        # ── 3. Patient demographics ──────────────────────────────────────
        demo_rows = conn.execute("SELECT sex, age FROM patients").fetchall()
        demo = {"Men": 0, "Women": 0, "Children": 0, "Unknown": 0}
        for r in demo_rows:
            age = r["age"]
            if age and int(age) < 18:
                demo["Children"] += 1
            elif r["sex"] == "Male":
                demo["Men"] += 1
            elif r["sex"] == "Female":
                demo["Women"] += 1
            else:
                demo["Unknown"] += 1

        # ── 4. Case type / procedure popularity (all time + by year) ─────
        # All-time procedure count
        proc_all = {}
        # Year-specific procedure count (for trend)
        proc_year = {}
        all_cases = conn.execute(
            "SELECT procedures_json, custom_procedure, "
            "strftime('%Y',created_at) yr FROM cases"
        ).fetchall()
        for r in all_cases:
            procs = _json.loads(r["procedures_json"] or "[]")
            if r["custom_procedure"]:
                procs.append("Custom")
            for p in procs:
                proc_all[p] = proc_all.get(p, 0) + 1
                if r["yr"] == yr:
                    proc_year[p] = proc_year.get(p, 0) + 1

        top_procedures_alltime = sorted(proc_all.items(), key=lambda x: x[1], reverse=True)[:10]
        top_procedures_year    = sorted(proc_year.items(), key=lambda x: x[1], reverse=True)[:10]

        # Monthly case type trend for top-5 procedures (sparkline data)
        top5_procs = [p for p, _ in top_procedures_alltime[:5]]
        case_type_monthly = {p: [0]*12 for p in top5_procs}
        for r in all_cases:
            if r["yr"] != yr:
                continue
            procs = _json.loads(r["procedures_json"] or "[]")
            month_raw = conn.execute(
                "SELECT strftime('%m',created_at) m FROM cases WHERE procedures_json=? LIMIT 1",
                (r["procedures_json"],)
            ).fetchone()
            # Use a simpler approach — fetch monthly breakdown per procedure type
        # Cleaner monthly case type approach
        case_type_monthly_clean = {}
        for r2 in conn.execute(
            "SELECT procedures_json, strftime('%m',created_at) m FROM cases "
            "WHERE strftime('%Y',created_at)=?", (yr,)
        ).fetchall():
            procs = _json.loads(r2["procedures_json"] or "[]")
            mo = int(r2["m"]) - 1
            for p in procs:
                if p not in case_type_monthly_clean:
                    case_type_monthly_clean[p] = [0]*12
                case_type_monthly_clean[p][mo] += 1
        # Keep only top 5
        case_type_monthly_top5 = {
            p: case_type_monthly_clean.get(p, [0]*12)
            for p in top5_procs
        }

        # Revenue by procedure type (approximate: total_cost divided evenly)
        proc_revenue = {}
        for r in conn.execute("SELECT procedures_json, total_cost FROM cases").fetchall():
            procs = _json.loads(r["procedures_json"] or "[]") or ["Unspecified"]
            share = (r["total_cost"] or 0) / len(procs)
            for p in procs:
                proc_revenue[p] = proc_revenue.get(p, 0) + share
        top_proc_revenue = sorted(proc_revenue.items(), key=lambda x: x[1], reverse=True)[:8]

        # ── 5. Doctor performance ────────────────────────────────────────
        doctor_perf = conn.execute(
            """SELECT d.name, d.color,
                      COUNT(c.id) as case_count,
                      SUM(CASE WHEN c.status='Active' THEN 1 ELSE 0 END) as active_cases,
                      SUM(CASE WHEN c.status='Closed' THEN 1 ELSE 0 END) as closed_cases,
                      COALESCE(SUM(c.total_cost),0) as total_billed,
                      COALESCE((SELECT SUM(p.amount) FROM payments p
                                 WHERE p.case_id = c.id), 0) as collected
               FROM cases c JOIN doctors d ON d.id = c.doctor_id
               GROUP BY c.doctor_id ORDER BY case_count DESC"""
        ).fetchall()

        # ── 6. Case status distribution ──────────────────────────────────
        status_dist = {
            r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) c FROM cases GROUP BY status"
            ).fetchall()
        }

        # ── 7. Payment method distribution ──────────────────────────────
        pay_methods = conn.execute(
            "SELECT method, COUNT(*) c, COALESCE(SUM(amount),0) s "
            "FROM payments GROUP BY method ORDER BY s DESC"
        ).fetchall()

        # ── 8. Average time to case closure (days) ───────────────────────
        closure_rows = conn.execute(
            "SELECT created_at, closed_at FROM cases "
            "WHERE status='Closed' AND closed_at != '' AND closed_at IS NOT NULL"
        ).fetchall()
        if closure_rows:
            from datetime import datetime as dt_dt
            deltas = []
            for r in closure_rows:
                try:
                    d1 = dt_dt.strptime(r["created_at"][:10], "%Y-%m-%d")
                    d2 = dt_dt.strptime(r["closed_at"][:10], "%Y-%m-%d")
                    deltas.append((d2 - d1).days)
                except Exception:
                    pass
            avg_days_to_close = round(sum(deltas) / len(deltas), 1) if deltas else 0
        else:
            avg_days_to_close = 0

        # ── 9. Collection rate and key KPIs ─────────────────────────────
        totals = conn.execute(
            "SELECT COALESCE(SUM(total_cost),0) billed, COUNT(*) cnt FROM cases"
        ).fetchone()
        collected_all = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments"
        ).fetchone()["s"]
        avg_case_value  = round(totals["billed"] / totals["cnt"], 2) if totals["cnt"] else 0
        collection_rate = round(
            collected_all / totals["billed"] * 100 if totals["billed"] else 0, 1
        )
        closure_rate = round(
            status_dist.get("Closed", 0) /
            max(status_dist.get("Closed", 0) + status_dist.get("Active", 0), 1) * 100, 1
        )

        # ── 10. Top patients by revenue ──────────────────────────────────
        top_patients = conn.execute(
            """SELECT p.name, p.mobile, p.sex,
                      COALESCE(SUM(pay.amount),0) as paid
               FROM payments pay
               JOIN cases c ON c.id = pay.case_id
               JOIN patients p ON p.id = c.patient_id
               GROUP BY c.patient_id ORDER BY paid DESC LIMIT 5"""
        ).fetchall()

        # ── 11. Available years ──────────────────────────────────────────
        years_raw = conn.execute(
            "SELECT DISTINCT strftime('%Y',created_at) y FROM patients "
            "UNION SELECT DISTINCT strftime('%Y',payment_date) y FROM payments "
            "ORDER BY y DESC"
        ).fetchall()
        available_years = [int(r["y"]) for r in years_raw if r["y"]]

        # ── 12. Monthly case type trend for chart ────────────────────────
        # (simplified to yearly procedure count per month for top 5)
        procedure_trend_labels = [p for p, _ in top_procedures_alltime[:5]]

    return {
        "year":                 year,
        "available_years":      available_years or [year],
        "monthly_trend":        monthly_trend,
        "dow_trend":            dow_trend,
        "demographics":         demo,
        "top_procedures":       [{"name": p, "count": c} for p, c in top_procedures_alltime],
        "top_procedures_year":  [{"name": p, "count": c} for p, c in top_procedures_year],
        "case_type_monthly":    case_type_monthly_top5,
        "top_proc_revenue":     [{"name": p, "revenue": round(r, 2)} for p, r in top_proc_revenue],
        "doctor_perf":          [dict(r) for r in doctor_perf],
        "status_dist":          status_dist,
        "pay_methods":          [dict(r) for r in pay_methods],
        "avg_case_value":       avg_case_value,
        "collection_rate":      collection_rate,
        "closure_rate":         closure_rate,
        "avg_days_to_close":    avg_days_to_close,
        "total_patients":       sum(demo.values()),
        "top_patients":         [dict(r) for r in top_patients],
        "procedure_trend_labels": procedure_trend_labels,
    }

    with get_conn() as conn:

        # 1. Monthly footfalls (new patients registered) + revenue
        monthly_patients = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',created_at) m, COUNT(*) c FROM patients "
                "WHERE strftime('%Y',created_at)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        monthly_revenue = {
            r["m"]: r["s"] for r in conn.execute(
                "SELECT strftime('%m',payment_date) m, COALESCE(SUM(amount),0) s "
                "FROM payments WHERE strftime('%Y',payment_date)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        monthly_cases = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',created_at) m, COUNT(*) c FROM cases "
                "WHERE strftime('%Y',created_at)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        month_labels = ["Jan","Feb","Mar","Apr","May","Jun",
                         "Jul","Aug","Sep","Oct","Nov","Dec"]
        monthly_trend = [
            {
                "month":    month_labels[i],
                "patients": monthly_patients.get(f"{i+1:02d}", 0),
                "revenue":  round(monthly_revenue.get(f"{i+1:02d}", 0), 2),
                "cases":    monthly_cases.get(f"{i+1:02d}", 0),
            }
            for i in range(12)
        ]

        # 2. Day-of-week trend for appointments (0=Sun … 6=Sat in SQLite strftime %w)
        day_labels = ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"]
        dow_appts = {
            r["d"]: r["c"] for r in conn.execute(
                "SELECT strftime('%w',appt_date) d, COUNT(*) c FROM appointments "
                "WHERE strftime('%Y',appt_date)=? GROUP BY d", (yr,)
            ).fetchall()
        }
        dow_payments = {
            r["d"]: r["s"] for r in conn.execute(
                "SELECT strftime('%w',payment_date) d, COALESCE(SUM(amount),0) s "
                "FROM payments WHERE strftime('%Y',payment_date)=? GROUP BY d", (yr,)
            ).fetchall()
        }
        dow_trend = [
            {
                "day":      day_labels[i],
                "appts":    dow_appts.get(str(i), 0),
                "revenue":  round(dow_payments.get(str(i), 0), 2),
            }
            for i in range(7)
        ]

        # 3. Patient demographics — Men / Women / Children (under 18)
        demo_rows = conn.execute(
            "SELECT sex, age FROM patients WHERE is_historic_import=0 OR 1=1"
        ).fetchall()
        demo = {"Men": 0, "Women": 0, "Children": 0, "Unknown": 0}
        for r in demo_rows:
            age = r["age"]
            if age and int(age) < 18:
                demo["Children"] += 1
            elif r["sex"] == "Male":
                demo["Men"] += 1
            elif r["sex"] == "Female":
                demo["Women"] += 1
            else:
                demo["Unknown"] += 1

        # 4. Procedure popularity (all time)
        proc_map = {}
        for r in conn.execute("SELECT procedures_json, custom_procedure FROM cases").fetchall():
            import json as _json
            procs = _json.loads(r["procedures_json"] or "[]")
            if r["custom_procedure"]:
                procs.append("Custom: " + r["custom_procedure"])
            for p in procs:
                proc_map[p] = proc_map.get(p, 0) + 1
        top_procedures = sorted(proc_map.items(), key=lambda x: x[1], reverse=True)[:10]

        # 5. Doctor performance (all time)
        doctor_perf = conn.execute(
            """SELECT d.name, COUNT(c.id) as case_count,
                      COALESCE(SUM(c.total_cost),0) as total_billed,
                      COALESCE((SELECT SUM(p.amount) FROM payments p
                                 WHERE p.case_id = c.id), 0) as collected
               FROM cases c JOIN doctors d ON d.id = c.doctor_id
               GROUP BY c.doctor_id ORDER BY case_count DESC"""
        ).fetchall()

        # 6. Case status distribution
        status_dist = {
            r["status"]: r["c"] for r in conn.execute(
                "SELECT status, COUNT(*) c FROM cases GROUP BY status"
            ).fetchall()
        }

        # 7. Average case value and collection rate
        totals = conn.execute(
            "SELECT COALESCE(SUM(total_cost),0) billed, COUNT(*) cnt FROM cases"
        ).fetchone()
        collected_all = conn.execute(
            "SELECT COALESCE(SUM(amount),0) s FROM payments"
        ).fetchone()["s"]
        avg_case_value = round(totals["billed"] / totals["cnt"], 2) if totals["cnt"] else 0
        collection_rate = round(
            collected_all / totals["billed"] * 100 if totals["billed"] else 0, 1
        )

        # 8. New vs returning patients per month (year)
        # "Returning" = patient has cases before the month in question
        # Approximated simply: total new registrations vs total appointments for existing patients
        monthly_appointments = {
            r["m"]: r["c"] for r in conn.execute(
                "SELECT strftime('%m',appt_date) m, COUNT(*) c FROM appointments "
                "WHERE strftime('%Y',appt_date)=? GROUP BY m", (yr,)
            ).fetchall()
        }
        for entry in monthly_trend:
            idx = month_labels.index(entry["month"])
            entry["appointments"] = monthly_appointments.get(f"{idx+1:02d}", 0)

        # 9. Top 5 patients by revenue (all time)
        top_patients = conn.execute(
            """SELECT p.name, p.mobile,
                      COALESCE(SUM(pay.amount),0) as paid
               FROM payments pay
               JOIN cases c ON c.id = pay.case_id
               JOIN patients p ON p.id = c.patient_id
               GROUP BY c.patient_id
               ORDER BY paid DESC LIMIT 5"""
        ).fetchall()

        # 10. Available years for the year selector
        years_raw = conn.execute(
            "SELECT DISTINCT strftime('%Y', created_at) y FROM patients "
            "UNION SELECT DISTINCT strftime('%Y', payment_date) y FROM payments "
            "ORDER BY y DESC"
        ).fetchall()
        available_years = [int(r["y"]) for r in years_raw if r["y"]]


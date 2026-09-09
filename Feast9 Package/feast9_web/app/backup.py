"""
Backups — interim/incremental protection for the SQLite database.

Two mechanisms:
1. On-demand SQLite backup — streams the live database as-is.
2. On-demand Excel export — human-readable "Plan B" spreadsheet.
3. Automatic daily snapshot — rotates the last 14 days.
"""
import os
from datetime import datetime

from app.config import DB_PATH, BACKUPS_DIR

AUTO_PREFIX = "auto_"
MANUAL_PREFIX = "manual_"
AUTO_RETENTION = 14

_FILENAME_RE = __import__('re').compile(r"^[a-zA-Z0-9_.\-]+$")


def _timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def create_backup(prefix: str) -> str:
    import sqlite3
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    filename = f"{prefix}{_timestamp()}.db"
    dest_path = os.path.join(BACKUPS_DIR, filename)
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(dest_path)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest_path


def list_backups() -> list:
    os.makedirs(BACKUPS_DIR, exist_ok=True)
    items = []
    for fname in os.listdir(BACKUPS_DIR):
        if not fname.endswith(".db"):
            continue
        full = os.path.join(BACKUPS_DIR, fname)
        kind = "auto" if fname.startswith(AUTO_PREFIX) else "manual"
        items.append({
            "filename": fname,
            "kind": kind,
            "size_bytes": os.path.getsize(full),
            "modified_at": datetime.fromtimestamp(
                os.path.getmtime(full)
            ).strftime("%Y-%m-%d %H:%M:%S"),
        })
    items.sort(key=lambda x: x["modified_at"], reverse=True)
    return items


def safe_backup_path(filename: str):
    if not filename or not _FILENAME_RE.match(filename) or not filename.endswith(".db"):
        return None
    path = os.path.join(BACKUPS_DIR, filename)
    if os.path.abspath(path) != path or not os.path.exists(path):
        return None
    return path


def delete_backup(filename: str) -> bool:
    path = safe_backup_path(filename)
    if not path:
        return False
    os.remove(path)
    return True


def prune_auto_backups(keep: int = AUTO_RETENTION):
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    for old in autos[keep:]:
        try:
            os.remove(os.path.join(BACKUPS_DIR, old["filename"]))
        except OSError:
            pass


def maybe_run_daily_backup():
    today = _today()
    existing = [
        f for f in os.listdir(BACKUPS_DIR)
        if f.startswith(AUTO_PREFIX) and today in f
    ] if os.path.isdir(BACKUPS_DIR) else []
    if existing:
        return
    if not os.path.exists(DB_PATH):
        return
    try:
        create_backup(AUTO_PREFIX)
        prune_auto_backups()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Excel "Plan B" export
# ---------------------------------------------------------------------------
def generate_excel_backup() -> bytes:
    """Returns bytes of an .xlsx workbook with:
      Sheet 1 — All patients + case details (one row per case, active first).
      Sheet 2 — Patients with no cases.
      Sheet 3 — Colour legend.
    Readable in any spreadsheet without needing the app."""
    import io
    import json
    from datetime import date
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from app.db import get_conn   # late import avoids circular dependency

    GREEN_DARK  = "2E7D32"
    GREEN_LIGHT = "E8F5E9"
    AMBER_LIGHT = "FFF8E1"
    RED_LIGHT   = "FDECEA"
    WHITE       = "FFFFFF"
    today_str   = date.today().isoformat()

    # ── style helpers ───────────────────────────────────────────────────────
    def header_style(cell, bg=GREEN_DARK):
        cell.font      = Font(bold=True, color="FFFFFF", name="Calibri", size=10)
        cell.fill      = PatternFill("solid", start_color=bg)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def thin_border():
        s = Side(style="thin", color="CCCCCC")
        return Border(left=s, right=s, top=s, bottom=s)

    def data_cell(cell, val="", bg=None, align="left"):
        cell.value     = val if val is not None else ""
        cell.font      = Font(name="Calibri", size=9)
        cell.alignment = Alignment(horizontal=align, vertical="center", wrap_text=True)
        cell.border    = thin_border()
        if bg:
            cell.fill = PatternFill("solid", start_color=bg)

    def row_bg(status, follow_up):
        if status == "Closed":
            return WHITE
        if follow_up and follow_up < today_str:
            return RED_LIGHT
        if follow_up and follow_up == today_str:
            return AMBER_LIGHT
        return GREEN_LIGHT

    # ── fetch all data in one connection ────────────────────────────────────
    with get_conn() as conn:
        case_rows = conn.execute("""
            SELECT
                p.name, p.age, p.sex, p.mobile, p.email, p.address,
                p.last_visited_date,
                p.emergency_contact_name, p.emergency_contact_number,
                p.medical_conditions_other, p.allergies_other,
                c.id AS case_id, c.title AS case_title, c.status, c.doctor_id,
                c.total_cost, c.follow_up_date, c.next_action_note,
                c.created_at AS case_opened, c.closed_at,
                c.procedures_json, c.custom_procedure
            FROM cases c
            JOIN patients p ON p.id = c.patient_id
            ORDER BY (c.status='Closed'), p.name, c.updated_at DESC
        """).fetchall()

        no_case_rows = conn.execute("""
            SELECT p.* FROM patients p
            WHERE NOT EXISTS (SELECT 1 FROM cases c WHERE c.patient_id = p.id)
            ORDER BY p.name
        """).fetchall()

        pay_map = {
            r["case_id"]: r["s"]
            for r in conn.execute(
                "SELECT case_id, COALESCE(SUM(amount),0) s "
                "FROM payments GROUP BY case_id"
            ).fetchall()
        }
        doc_map = {
            r["id"]: r["name"]
            for r in conn.execute("SELECT id, name FROM doctors").fetchall()
        }

    wb = Workbook()

    # ── Sheet 1: Patients & Cases ────────────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Patients & Cases"
    ws1.freeze_panes = "A2"

    COLS1 = [
        ("Patient Name", 22), ("Age", 5), ("Sex", 7), ("Mobile", 14),
        ("Email", 24), ("Address", 26), ("Last Visited", 13),
        ("Emergency Contact", 20), ("EC Number", 14),
        ("Medical Conditions", 26), ("Allergies", 20),
        ("Case Title", 26), ("Status", 10), ("Doctor", 18),
        ("Procedures", 28), ("Total Cost (Rs.)", 15), ("Paid (Rs.)", 12),
        ("Balance (Rs.)", 12), ("Follow-up Date", 13), ("Next Action", 28),
        ("Case Opened", 13), ("Case Closed", 13),
    ]
    ws1.row_dimensions[1].height = 36
    for ci, (label, width) in enumerate(COLS1, 1):
        header_style(ws1.cell(row=1, column=ci, value=label))
        ws1.column_dimensions[get_column_letter(ci)].width = width

    MONEY_COLS = {16, 17, 18}
    for ri, r in enumerate(case_rows, 2):
        procs = json.loads(r["procedures_json"] or "[]")
        if r["custom_procedure"]:
            procs.append(f"(Custom: {r['custom_procedure']})")
        paid    = pay_map.get(r["case_id"], 0)
        balance = round((r["total_cost"] or 0) - paid, 2)
        doctor  = doc_map.get(r["doctor_id"], "")
        bg      = row_bg(r["status"], r["follow_up_date"])
        values  = [
            r["name"], r["age"] or "", r["sex"] or "", r["mobile"],
            r["email"] or "", r["address"] or "", r["last_visited_date"] or "",
            r["emergency_contact_name"] or "", r["emergency_contact_number"] or "",
            r["medical_conditions_other"] or "", r["allergies_other"] or "",
            r["case_title"], r["status"], doctor,
            ", ".join(procs) or "—",
            r["total_cost"] or 0, paid, balance,
            r["follow_up_date"] or "", r["next_action_note"] or "",
            r["case_opened"] or "", r["closed_at"] or "",
        ]
        for ci, val in enumerate(values, 1):
            cell = ws1.cell(row=ri, column=ci)
            data_cell(cell, val, bg=bg, align="right" if ci in MONEY_COLS else "left")
            if ci in MONEY_COLS and isinstance(val, (int, float)):
                cell.number_format = "#,##0.00"
        ws1.row_dimensions[ri].height = 18

    # ── Sheet 2: Patients with no cases ─────────────────────────────────────
    ws2 = wb.create_sheet("Patients (No Cases)")
    ws2.freeze_panes = "A2"
    COLS2 = [
        ("Patient Name", 22), ("Age", 5), ("Sex", 7), ("Mobile", 14),
        ("Email", 24), ("Address", 30), ("Last Visited", 13),
        ("Emergency Contact", 20), ("EC Number", 14),
        ("Medical Conditions", 26), ("Allergies", 20),
    ]
    ws2.row_dimensions[1].height = 36
    for ci, (label, width) in enumerate(COLS2, 1):
        header_style(ws2.cell(row=1, column=ci, value=label))
        ws2.column_dimensions[get_column_letter(ci)].width = width
    for ri, p in enumerate(no_case_rows, 2):
        for ci, val in enumerate([
            p["name"], p["age"] or "", p["sex"] or "", p["mobile"],
            p["email"] or "", p["address"] or "", p["last_visited_date"] or "",
            p["emergency_contact_name"] or "", p["emergency_contact_number"] or "",
            p["medical_conditions_other"] or "", p["allergies_other"] or "",
        ], 1):
            data_cell(ws2.cell(row=ri, column=ci), val)
        ws2.row_dimensions[ri].height = 18

    # ── Sheet 3: Legend ──────────────────────────────────────────────────────
    ws3 = wb.create_sheet("Legend")
    ws3.column_dimensions["A"].width = 28
    ws3.column_dimensions["B"].width = 44
    LEGEND = [
        ("Colour",       "Meaning"),
        ("Green row",    "Active case — no overdue follow-up"),
        ("Amber row",    "Active case — follow-up due TODAY"),
        ("Red row",      "Active case — follow-up is OVERDUE"),
        ("White row",    "Closed case"),
    ]
    LEGEND_BGS = {2: GREEN_LIGHT, 3: AMBER_LIGHT, 4: RED_LIGHT, 5: WHITE}
    for ri, (a, b) in enumerate(LEGEND, 1):
        ca = ws3.cell(row=ri, column=1, value=a)
        cb = ws3.cell(row=ri, column=2, value=b)
        if ri == 1:
            header_style(ca)
            header_style(cb)
        else:
            for cell in (ca, cb):
                cell.font   = Font(name="Calibri", size=9)
                cell.border = thin_border()
                if ri in LEGEND_BGS:
                    cell.fill = PatternFill("solid", start_color=LEGEND_BGS[ri])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()

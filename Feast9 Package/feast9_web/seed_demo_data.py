"""
Optional: populates the app with a handful of sample doctors, patients,
cases, payments, and prescriptions so you have something to look at on
first run, instead of staring at an empty dashboard.

Run this AFTER you've completed the one-time setup screen (so a user
account already exists), and BEFORE you start entering real patient data.

Usage:
    python seed_demo_data.py
"""
from app import db

def run():
    db.init_db()

    if db.count_patients() > 0:
        print("There's already patient data in this database — skipping seed "
              "to avoid creating duplicates. Delete the 'instance' folder "
              "first if you want a totally clean slate.")
        return

    doc1 = db.add_doctor("Dr. Anjali Rao")
    doc2 = db.add_doctor("Dr. Vivek Menon")

    p1 = db.add_patient("Ravi Kumar", 34, "Male", "9876543210",
                         "ravi@example.com", "MG Road, Kochi", "2026-06-15",
                         medical_conditions=["Diabetes"], emergency_contact_name="Priya Kumar",
                         emergency_contact_relation="Wife", emergency_contact_number="9876543299")
    p2 = db.add_patient("Meera Menon", 29, "Female", "9123456780",
                         "", "Kakkanad, Kochi", "2026-06-10",
                         allergies=["Penicillin", "Local Anesthetics (Lignocaine)"],
                         is_nursing=1, emergency_contact_name="Anil Menon",
                         emergency_contact_relation="Husband", emergency_contact_number="9123456788")
    p3 = db.add_patient("Suresh Pillai", 52, "Male", "9988776655",
                         "suresh@example.com", "Edappally, Kochi", "2026-05-28",
                         medical_conditions=["Blood Pressure (High/Low)", "Heart Disease"],
                         medical_conditions_other="On blood thinners — confirm with physician before extraction")

    c1 = db.add_case(p1, "Upper molar RCT & Crown", "Active",
                      ["Root Canal Treatment (RCT)", "Crown — Ceramic/Zirconia"],
                      "Patient prefers ceramic for aesthetics", doc1,
                      12000, "Crown fitting at next visit", "2026-06-25")
    db.add_payment(c1, 5000, "2026-06-15", "Cash", "Advance payment")
    db.add_prescription(c1, "2026-06-15",
                         "Amoxicillin 500mg TDS x5 days\nIbuprofen 400mg SOS for pain")
    db.add_visit_note(c1, "2026-06-15", "First sitting: access opening and cleaning done.")

    # A small sample "drawn" signature so the demo consent record behaves
    # exactly like a real one (print/view works, thumbnail shows correctly).
    from app.config import CONSENTS_DIR
    import os
    import uuid
    try:
        from PIL import Image, ImageDraw
        os.makedirs(CONSENTS_DIR, exist_ok=True)
        sig = Image.new("RGBA", (300, 100), (255, 255, 255, 0))
        d = ImageDraw.Draw(sig)
        d.line([(10, 80), (60, 20), (110, 80), (160, 30), (210, 70), (260, 40)],
               fill=(27, 43, 30, 255), width=4)
        sig_filename = f"consent_{c1}_{uuid.uuid4().hex}.png"
        sig.save(os.path.join(CONSENTS_DIR, sig_filename), format="PNG")
    except Exception:
        sig_filename = None

    db.add_consent(
        c1,
        "I, Ravi Kumar, confirm that Dr. Anjali Rao has explained to me the nature, "
        "purpose, expected benefits, possible risks and complications, and reasonable "
        "alternatives of the proposed procedure(s): Upper molar RCT & Crown.\n\nI "
        "voluntarily consent to undergo the above treatment.",
        "2026-06-15", "drawn", sig_filename, "Ravi Kumar", witness_name="",
        notes="Sample consent record for demo purposes",
    )

    c2 = db.add_case(p1, "Routine Scaling", "Closed",
                      ["Scaling & Polishing"], "", doc1, 1200, "", "")
    db.add_payment(c2, 1200, "2026-05-01", "UPI", "Paid in full")

    c3 = db.add_case(p2, "Wisdom Tooth Extraction", "Active",
                      ["Wisdom Tooth Extraction"], "Mild swelling, monitor",
                      doc2, 4500, "Review healing", "2026-06-19")
    db.add_payment(c3, 2000, "2026-06-10", "Card", "")
    db.add_visit_note(c3, "2026-06-10", "First sitting: examination and X-ray taken.")
    db.add_visit_note(c3, "2026-06-12", "Follow-up: bony impaction identified, surgical "
                       "extraction recommended and discussed with patient.")
    db.revise_case_cost(c3, 9000, "Surgical extraction required after bony impaction "
                         "found on X-ray", "2026-06-12")

    c4 = db.add_case(p2, "Teeth Whitening", "Active",
                      ["Teeth Whitening"], "", doc1, 6000, "", "2026-07-05")

    c5 = db.add_case(p3, "Lower bridge", "Active",
                      ["Bridge"], "", doc2, 18000, "Impression taken, awaiting lab", "2026-06-12")
    db.add_payment(c5, 9000, "2026-05-28", "Bank Transfer", "50% advance")

    from datetime import date, timedelta
    today = date.today()
    db.add_appointment(p1, doc1, today.isoformat(), "10:30", "11:00",
                        "Crown fitting", "", "Scheduled")
    db.add_appointment(p2, doc2, (today + timedelta(days=1)).isoformat(), "15:00", "",
                        "Review healing", "", "Scheduled")
    db.add_appointment(p3, doc1, (today + timedelta(days=2)).isoformat(), "09:30", "10:00",
                        "Bridge fitting", "", "Scheduled")

    print("Sample data added:")
    print(f"  Doctors:  Dr. Anjali Rao, Dr. Vivek Menon")
    print(f"  Patients: Ravi Kumar, Meera Menon, Suresh Pillai (with sample medical "
          f"history, an allergy, and emergency contacts)")
    print(f"  Cases:    5 (with payments, a prescription, visit notes, a tracked cost "
          f"revision, and a signed consent form)")
    print(f"  Appointments: 3 (on the calendar, color-coded by doctor)")
    print()
    print("Refresh the app in your browser to see the dashboard populated.")


if __name__ == "__main__":
    run()

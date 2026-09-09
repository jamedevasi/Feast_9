"""Static reference lists used throughout the app."""

SEX_OPTIONS = ["Male", "Female"]

CASE_STATUS_ACTIVE = "Active"
CASE_STATUS_CLOSED = "Closed"
CASE_STATUS_OPTIONS = [CASE_STATUS_ACTIVE, CASE_STATUS_CLOSED]

OTHER_PROCEDURE_LABEL = "Other / Custom"

# Seeded into the procedure_types table on first run. After that, the list is
# fully editable from the "Manage Case/Procedure Types" screen, so editing
# this list later has no effect on an existing database.
DEFAULT_PROCEDURE_TYPES = [
    "Consultation / Check-up",
    "Scaling & Polishing",
    "Filling (Composite)",
    "Filling (GIC)",
    "Root Canal Treatment (RCT)",
    "Root Canal Re-treatment",
    "Tooth Extraction (Simple)",
    "Surgical Extraction",
    "Wisdom Tooth Extraction",
    "Crown — Metal",
    "Crown — Ceramic/Zirconia",
    "Bridge",
    "Complete Denture",
    "Partial Denture",
    "Dental Implant",
    "Teeth Whitening",
    "Orthodontic Treatment (Braces)",
    "Orthodontic Treatment (Aligners)",
    "Veneers",
    "Night Guard / Mouth Guard",
    "Pediatric Dental Treatment",
    "Periodontal (Gum) Treatment",
    "Fluoride Treatment",
    "X-Ray / Imaging",
    "Post & Core",
    "Apicoectomy",
]

PAYMENT_METHODS = ["Cash", "Card", "UPI", "Bank Transfer", "Cheque", "Insurance", "Other"]

# Default boilerplate shown when starting a new consent record — kept
# editable per case since what matters legally is the exact wording the
# patient actually agreed to, not a link to a template that could change
# later. {patient_name}, {doctor_name}, {case_title}, {procedures} are
# filled in before display.
DEFAULT_CONSENT_TEXT = """I, {patient_name}, confirm that {doctor_name} has explained to me \
the nature, purpose, expected benefits, possible risks and complications, \
and reasonable alternatives (including no treatment) of the proposed \
procedure(s): {case_title} ({procedures}).

I have had the opportunity to ask questions and have received satisfactory \
answers. I understand that no guarantee has been made regarding the exact \
outcome of this treatment.

I voluntarily consent to undergo the above treatment to be performed by \
{doctor_name} or other qualified staff of this practice as deemed necessary."""

# Password-recovery security questions offered at setup time. "Other" lets
# the practitioner write their own.
SECURITY_QUESTIONS = [
    "What city were you born in?",
    "What was the name of your first pet?",
    "What is your mother's maiden name?",
    "What was the name of your first school?",
    "What was your childhood nickname?",
    "Other (write your own)",
]

# Standard medical history checklist shown on patient registration —
# common conditions a dentist needs to know about before treatment
# (bleeding risk, drug interactions, anesthesia precautions, etc).
MEDICAL_CONDITIONS = [
    "Asthma",
    "Diabetes",
    "Blood Pressure (High/Low)",
    "Heart Disease",
    "Kidney Disease",
    "Liver Disease",
    "Epilepsy",
    "Psychiatric Problems",
    "Bleeding Disorders",
    "Rheumatic Fever",
    "Corticosteroid Treatment",
    "Gastric Ulcer",
    "Thyroid Disorder",
    "Tuberculosis",
    "Hepatitis / Jaundice",
]

# Standard list of drug classes that commonly cause allergic reactions —
# shown as a multi-select on patient registration, separate from a free
# text field for anything else.
ALLERGY_DRUGS = [
    "Penicillin",
    "Sulfa Drugs",
    "Aspirin",
    "NSAIDs (Ibuprofen / Diclofenac)",
    "Local Anesthetics (Lignocaine)",
    "Latex",
    "Iodine",
    "Codeine",
]

# ── DPDP Act 2023 Phase 1 ─────────────────────────────────────────────────
DPDP_NOTICE_TEXT = """What data we collect:
Your name, contact number, age/date of birth, sex, address, medical history, allergies, and emergency contact. Treatment records including diagnoses, prescriptions, X-rays, payments, and consent forms.

Why we collect it:
To provide safe and effective dental care, maintain your treatment history, process payments, and meet our legal obligations.

How long we keep it:
Clinical records are retained for a minimum of 7 years from your last visit as required by law. Communication records are kept only as long as necessary.

Who we share it with:
We do not sell or share your data with third parties except where required by law or where you have separately consented to referrals or insurance claims.

Your rights under the DPDP Act 2023:
Right to access the data we hold, request corrections, withdraw consent for non-treatment communications, and request erasure (subject to legal retention requirements). Contact us directly to exercise any right.

This notice is provided under Section 5 of the Digital Personal Data Protection Act 2023."""

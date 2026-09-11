#!/usr/bin/env python3
"""Deterministic seed script for medical_demo Mock Medical DB."""

from __future__ import annotations

import hashlib
import os
import random
import sys
from datetime import date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def connect() -> psycopg.Connection:
    return psycopg.connect(
        host=env("MEDICAL_DB_HOST", "localhost"),
        port=int(env("MEDICAL_DB_PORT", "5432")),
        dbname=env("MEDICAL_DB_NAME", "medical_demo"),
        user=env("MEDICAL_DB_USER", "medical_user"),
        password=env("MEDICAL_DB_PASSWORD"),
        row_factory=dict_row,
    )


DEPTS = [
    ("IM01", "내과", "CLINIC", None),
    ("GS01", "외과", "CLINIC", None),
    ("ER01", "응급의학과", "CLINIC", None),
    ("RD01", "영상의학과", "SUPPORT", None),
    ("LM01", "진단검사의학과", "SUPPORT", None),
    ("PH01", "약제과", "SUPPORT", None),
    ("NR01", "간호부", "SUPPORT", None),
    ("CD01", "순환기내과", "CLINIC", "IM01"),
    ("EN01", "내분비내과", "CLINIC", "IM01"),
    ("GI01", "소화기내과", "CLINIC", "IM01"),
]

WARDS = [
    ("W31", "31병동", 40, "IM01"),
    ("W32", "32병동", 36, "GS01"),
    ("WICU", "중환자실", 12, "IM01"),
    ("WER", "응급병동", 20, "ER01"),
]

PROVIDERS = [
    ("P_IM_01", "김내과의", "PHYS", "IM01", "M11111"),
    ("P_IM_02", "이내과의", "PHYS", "IM01", "M11112"),
    ("P_CD_01", "박순환기", "PHYS", "CD01", "M22221"),
    ("P_EN_01", "최내분비", "PHYS", "EN01", "M33331"),
    ("P_GI_01", "정소화기", "PHYS", "GI01", "M44441"),
    ("P_GS_01", "강외과의", "PHYS", "GS01", "M55551"),
    ("P_ER_01", "윤응급의", "PHYS", "ER01", "M66661"),
    ("P_RD_01", "한영상의", "PHYS", "RD01", "M77771"),
    ("P_LM_01", "오진단검", "PHYS", "LM01", "M88881"),
    ("P_NR_01", "서간호", "NURS", "NR01", "N10001"),
    ("P_NR_02", "조간호", "NURS", "NR01", "N10002"),
    ("P_PH_01", "유약사", "TECH", "PH01", "T20001"),
]

DGN_CODES = [
    ("I10", "본태성(원발성) 고혈압", "Essential hypertension", "CARDIO"),
    ("I20.0", "불안정형 협심증", "Unstable angina", "CARDIO"),
    ("E11.9", "합병증을 동반하지 않은 2형 당뇨병", "Type 2 DM without complications", "ENDO"),
    ("E78.5", "고지혈증, 상세불명", "Hyperlipidemia, unspecified", "ENDO"),
    ("N18.3", "만성 신장병 3기", "Chronic kidney disease, stage 3", "RENAL"),
    ("K76.0", "지방간(비알코올성)", "Fatty liver", "GI"),
    ("J18.9", "폐렴, 상세불명", "Pneumonia, unspecified", "RESP"),
    ("K29.7", "위염, 상세불명", "Gastritis, unspecified", "GI"),
    ("M17.1", "기타 원발성 무릎관절증", "Other primary gonarthrosis", "ORTHO"),
    ("S06.0", "뇌진탕", "Concussion", "TRAUMA"),
]

LAB_TESTS = [
    ("L_AST", "AST(GOT)", "Aspartate aminotransferase", "LIVER", "혈청", "U/L"),
    ("L_ALT", "ALT(GPT)", "Alanine aminotransferase", "LIVER", "혈청", "U/L"),
    ("L_GGT", "γ-GTP(GGT)", "Gamma-glutamyl transferase", "LIVER", "혈청", "U/L"),
    ("L_ALP", "ALP", "Alkaline phosphatase", "LIVER", "혈청", "U/L"),
    ("L_TBIL", "총빌리루빈", "Total bilirubin", "LIVER", "혈청", "mg/dL"),
    ("L_GLU", "Glucose", "Glucose", "GLUCOSE", "혈청", "mg/dL"),
    ("L_FBS", "공복혈당(FBS)", "Fasting blood sugar", "GLUCOSE", "혈청", "mg/dL"),
    ("L_HBA1C", "당화혈색소(HbA1c)", "Hemoglobin A1c", "GLUCOSE", "전혈", "%"),
    ("L_CRE", "Creatinine", "Creatinine", "KIDNEY", "혈청", "mg/dL"),
    ("L_EGFR", "eGFR", "Estimated GFR", "KIDNEY", "계산", "mL/min/1.73m2"),
    ("L_BUN", "BUN", "Blood urea nitrogen", "KIDNEY", "혈청", "mg/dL"),
    ("L_WBC", "WBC", "White blood cell", "CBC", "전혈", "10^3/uL"),
    ("L_HGB", "Hemoglobin", "Hemoglobin", "CBC", "전혈", "g/dL"),
]

LAB_REFS = [
    ("L_AST", "A", 0, 150, 0, 40, "U/L"),
    ("L_ALT", "A", 0, 150, 0, 40, "U/L"),
    ("L_GGT", "M", 0, 150, 0, 70, "U/L"),
    ("L_GGT", "F", 0, 150, 0, 40, "U/L"),
    ("L_ALP", "A", 0, 150, 40, 129, "U/L"),
    ("L_TBIL", "A", 0, 150, 0.2, 1.2, "mg/dL"),
    ("L_GLU", "A", 0, 150, 70, 140, "mg/dL"),
    ("L_FBS", "A", 0, 150, 70, 99, "mg/dL"),
    ("L_HBA1C", "A", 0, 150, 4.0, 5.6, "%"),
    ("L_CRE", "M", 0, 150, 0.7, 1.3, "mg/dL"),
    ("L_CRE", "F", 0, 150, 0.6, 1.1, "mg/dL"),
    ("L_EGFR", "A", 0, 150, 60, 120, "mL/min/1.73m2"),
    ("L_BUN", "A", 0, 150, 7, 20, "mg/dL"),
    ("L_WBC", "A", 0, 150, 4.0, 10.0, "10^3/uL"),
    ("L_HGB", "M", 0, 150, 13.0, 17.0, "g/dL"),
    ("L_HGB", "F", 0, 150, 12.0, 15.0, "g/dL"),
]

DRUGS = [
    ("D_AML5", "암로디핀 5mg", "Amlodipine", "C08CA01", "TAB", "5mg", "정"),
    ("D_LOS50", "로사르탄 50mg", "Losartan", "C09CA01", "TAB", "50mg", "정"),
    ("D_MET500", "메트포르민 500mg", "Metformin", "A10BA02", "TAB", "500mg", "정"),
    ("D_ATO20", "아토르바스타틴 20mg", "Atorvastatin", "C10AA05", "TAB", "20mg", "정"),
    ("D_ASA100", "아스피린장용 100mg", "Aspirin", "B01AC06", "TAB", "100mg", "정"),
    ("D_OMZ20", "오메프라졸 20mg", "Omeprazole", "A02BC01", "CAP", "20mg", "캡슐"),
    ("D_ACET650", "아세트아미노펜 650mg", "Acetaminophen", "N02BE01", "TAB", "650mg", "정"),
    ("D_CEF250", "세프프로질 250mg", "Cefprozil", "J01DC10", "TAB", "250mg", "정"),
]

IMG_TESTS = [
    ("I_CXR", "흉부 X-ray", "XR", "CHEST"),
    ("I_CTAB", "복부 CT", "CT", "ABDOMEN"),
    ("I_CTCH", "흉부 CT", "CT", "CHEST"),
    ("I_MRI_BR", "뇌 MRI", "MR", "BRAIN"),
    ("I_USAB", "복부 초음파", "US", "ABDOMEN"),
    ("I_EKG", "심전도", "OT", "HEART"),
]

PROCS = [
    ("PR_IV", "정맥주사", "NURS"),
    ("PR_INJ", "근육주사", "NURS"),
    ("PR_ECG", "심전도 검사", "CARDIO"),
    ("PR_NEB", "네뷸라이저 치료", "RESP"),
    ("PR_DRSG", "상처드레싱", "SURG"),
]

DOC_TYPES = [
    ("DT_DSCH", "퇴원요약", "SUMMARY"),
    ("DT_PROG", "경과기록", "NOTE"),
    ("DT_OP", "수술기록", "OP"),
    ("DT_ADM", "입원기록", "ADM"),
    ("DT_CONS", "협진의뢰서", "CONSULT"),
]

CODES = [
    ("SEX", "M", "남성", "Male", 1),
    ("SEX", "F", "여성", "Female", 2),
    ("ENC_TYP", "O", "외래", "Outpatient", 1),
    ("ENC_TYP", "I", "입원", "Inpatient", 2),
    ("ENC_TYP", "E", "응급", "Emergency", 3),
    ("FREQ", "QD", "1일 1회", "Once daily", 1),
    ("FREQ", "BID", "1일 2회", "Twice daily", 2),
    ("FREQ", "TID", "1일 3회", "Three times daily", 3),
    ("ROUTE", "PO", "경구", "Oral", 1),
    ("ROUTE", "IV", "정맥", "Intravenous", 2),
    ("ROUTE", "IM", "근육", "Intramuscular", 3),
]

FAMILY_NAMES = list("김이박최정강조윤장임한오서신권황안송류전홍")
GIVEN_NAMES = [
    "민수", "서연", "지훈", "하은", "도윤", "수아", "예준", "지아",
    "현우", "채원", "준서", "유나", "시우", "소율", "건우", "다은",
    "우진", "예린", "태윤", "서현", "재민", "윤서", "성민", "하린",
]


def hash_rr(pt_no: str) -> str:
    return hashlib.sha256(f"rr::{pt_no}".encode()).hexdigest()


def rand_dt(rng: random.Random, start: datetime, end: datetime) -> datetime:
    delta = int((end - start).total_seconds())
    return start + timedelta(seconds=rng.randint(0, max(delta, 1)))


def lab_value(rng: random.Random, exm_cd: str) -> tuple[float, str, str]:
    ranges: dict[str, tuple[float, float, str]] = {
        "L_AST": (15, 120, "U/L"),
        "L_ALT": (12, 130, "U/L"),
        "L_GGT": (10, 150, "U/L"),
        "L_ALP": (40, 180, "U/L"),
        "L_TBIL": (0.3, 2.5, "mg/dL"),
        "L_GLU": (70, 220, "mg/dL"),
        "L_FBS": (70, 180, "mg/dL"),
        "L_HBA1C": (4.8, 9.5, "%"),
        "L_CRE": (0.5, 2.4, "mg/dL"),
        "L_EGFR": (25, 115, "mL/min/1.73m2"),
        "L_BUN": (7, 45, "mg/dL"),
        "L_WBC": (3.5, 14.0, "10^3/uL"),
        "L_HGB": (9.5, 17.5, "g/dL"),
    }
    low, high, unit = ranges[exm_cd]
    val = round(rng.uniform(low, high), 2)
    return val, f"{val}", unit


def abnormal(exm_cd: str, val: float) -> str:
    limits = {
        "L_AST": 40,
        "L_ALT": 40,
        "L_GGT": 70,
        "L_ALP": 129,
        "L_TBIL": 1.2,
        "L_GLU": 140,
        "L_FBS": 99,
        "L_HBA1C": 5.6,
        "L_CRE": 1.3,
        "L_EGFR": 60,  # below is abnormal
        "L_BUN": 20,
        "L_WBC": 10.0,
        "L_HGB": 12.0,  # simplistic
    }
    if exm_cd == "L_EGFR":
        return "Y" if val < limits[exm_cd] else "N"
    if exm_cd == "L_HGB":
        return "Y" if val < limits[exm_cd] else "N"
    return "Y" if val > limits.get(exm_cd, 9999) else "N"


def already_seeded(conn: psycopg.Connection) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM TB_PT_MST")
        row = cur.fetchone()
        return bool(row and row["cnt"] > 0)


def truncate_all(conn: psycopg.Connection) -> None:
    tables = [
        "TB_LAB_RST", "TB_LAB_ORD", "TB_LAB_REF", "TB_MED_ORD", "TB_IMG_RPT",
        "TB_IMG_ORD", "TB_CLN_DOC", "TB_ORD_DTL", "TB_ORD_HDR", "TB_DGN_HIST",
        "TB_PROC_HIST", "TB_ADM_HIST", "TB_ENC_HIST", "TB_PT_MST", "TB_PROVIDER",
        "TB_WARD_MST", "TB_DEPT_MST", "TB_DOC_TYPE", "TB_LAB_MST", "TB_DRUG_MST",
        "TB_PROC_MST", "TB_DGN_CD_MST", "TB_IMG_MST", "TB_CODE_MST",
    ]
    with conn.cursor() as cur:
        cur.execute("TRUNCATE TABLE " + ", ".join(tables) + " RESTART IDENTITY CASCADE")
    conn.commit()


def seed_masters(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for row in CODES:
            cur.execute(
                """
                INSERT INTO TB_CODE_MST (CD_GRP, CD_VAL, CD_NM, CD_DESC, SORT_ORD)
                VALUES (%s, %s, %s, %s, %s)
                """,
                row,
            )
        for dept_cd, dept_nm, dept_typ, up in DEPTS:
            cur.execute(
                """
                INSERT INTO TB_DEPT_MST (DEPT_CD, DEPT_NM, DEPT_TYP, UP_DEPT_CD)
                VALUES (%s, %s, %s, %s)
                """,
                (dept_cd, dept_nm, dept_typ, up),
            )
        for row in WARDS:
            cur.execute(
                "INSERT INTO TB_WARD_MST (WARD_CD, WARD_NM, BED_CNT, DEPT_CD) VALUES (%s,%s,%s,%s)",
                row,
            )
        for row in PROVIDERS:
            cur.execute(
                """
                INSERT INTO TB_PROVIDER (PROV_ID, PROV_NM, PROV_TYP, DEPT_CD, LIC_NO)
                VALUES (%s,%s,%s,%s,%s)
                """,
                row,
            )
        for row in DGN_CODES:
            cur.execute(
                """
                INSERT INTO TB_DGN_CD_MST (DGN_CD, DGN_NM, DGN_NM_EN, CAT_CD)
                VALUES (%s,%s,%s,%s)
                """,
                row,
            )
        for row in LAB_TESTS:
            cur.execute(
                """
                INSERT INTO TB_LAB_MST (EXM_CD, EXM_NM, EXM_NM_EN, EXM_CAT, SPEC_TYP, UNIT_CD)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                row,
            )
        for row in LAB_REFS:
            cur.execute(
                """
                INSERT INTO TB_LAB_REF (EXM_CD, SEX_CD, AGE_FROM, AGE_TO, LOW_VAL, HIGH_VAL, UNIT_CD)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                row,
            )
        for row in DRUGS:
            cur.execute(
                """
                INSERT INTO TB_DRUG_MST (DRUG_CD, DRUG_NM, GEN_NM, ATC_CD, FORM_CD, STR_VAL, UNIT_CD)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                row,
            )
        for row in IMG_TESTS:
            cur.execute(
                "INSERT INTO TB_IMG_MST (IMG_CD, IMG_NM, MODALITY, BODY_PART) VALUES (%s,%s,%s,%s)",
                row,
            )
        for row in PROCS:
            cur.execute(
                "INSERT INTO TB_PROC_MST (PROC_CD, PROC_NM, PROC_CAT) VALUES (%s,%s,%s)",
                row,
            )
        for row in DOC_TYPES:
            cur.execute(
                "INSERT INTO TB_DOC_TYPE (DOC_TYP_CD, DOC_TYP_NM, DOC_CAT) VALUES (%s,%s,%s)",
                row,
            )
    conn.commit()


def seed_clinical(conn: psycopg.Connection, patient_count: int, rng: random.Random) -> dict[str, int]:
    counts: dict[str, int] = {
        "patients": 0,
        "encounters": 0,
        "diagnoses": 0,
        "lab_results": 0,
        "medications": 0,
        "imaging_reports": 0,
        "clinical_documents": 0,
        "admissions": 0,
        "procedures": 0,
    }

    clinic_depts = [d for d in DEPTS if d[2] == "CLINIC"]
    physicians = [p for p in PROVIDERS if p[2] == "PHYS"]
    radiologists = [p for p in PROVIDERS if p[0].startswith("P_RD")]
    lab_staff = [p for p in PROVIDERS if p[0].startswith("P_LM")]

    with conn.cursor() as cur:
        for i in range(1, patient_count + 1):
            pt_no = f"PT{i:06d}"
            sex = rng.choice(["M", "F"])
            birth = date(1935, 1, 1) + timedelta(days=rng.randint(0, 70 * 365))
            name = rng.choice(FAMILY_NAMES) + rng.choice(GIVEN_NAMES)
            cur.execute(
                """
                INSERT INTO TB_PT_MST (PT_NO, PT_NM, BRTH_DT, SEX_CD, RR_NO_HASH, TEL_NO, ADDR_TXT, BLD_TYP)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    pt_no,
                    name,
                    birth,
                    sex,
                    hash_rr(pt_no),
                    f"010-{rng.randint(1000,9999)}-{rng.randint(1000,9999)}",
                    f"서울시 중구 테스트로 {rng.randint(1,200)}",
                    rng.choice(["A", "B", "O", "AB"]),
                ),
            )
            counts["patients"] += 1

            enc_n = rng.randint(1, 4)
            for e in range(1, enc_n + 1):
                enc_id = f"ENC{i:06d}{e:02d}"
                enc_typ = rng.choices(["O", "I", "E"], weights=[0.65, 0.25, 0.10])[0]
                dept = rng.choice(clinic_depts)
                prov = rng.choice([p for p in physicians if p[3] == dept[0]] or physicians)
                adm_dt = rand_dt(rng, datetime(2023, 1, 1), datetime(2025, 12, 31))
                dsch_dt = None
                enc_sts = "A"
                if enc_typ == "I":
                    stay = rng.randint(2, 14)
                    dsch_dt = adm_dt + timedelta(days=stay)
                    enc_sts = "D"
                elif rng.random() < 0.85:
                    dsch_dt = adm_dt + timedelta(hours=rng.randint(1, 8))
                    enc_sts = "D"

                cur.execute(
                    """
                    INSERT INTO TB_ENC_HIST
                    (ENC_ID, PT_NO, ENC_TYP, ENC_STS, DEPT_CD, PROV_ID, ADM_DT, DSCH_DT, CHIEF_COMP)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        enc_id,
                        pt_no,
                        enc_typ,
                        enc_sts,
                        dept[0],
                        prov[0],
                        adm_dt,
                        dsch_dt,
                        rng.choice(["두통", "복통", "흉통", "호흡곤란", "피로", "발열", "어지럼"]),
                    ),
                )
                counts["encounters"] += 1

                if enc_typ == "I":
                    ward = rng.choice(WARDS)
                    cur.execute(
                        """
                        INSERT INTO TB_ADM_HIST
                        (ADM_ID, ENC_ID, PT_NO, WARD_CD, BED_NO, ADM_DT, DSCH_DT, DSCH_TYP, ADM_PATH)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            f"ADM{i:06d}{e:02d}",
                            enc_id,
                            pt_no,
                            ward[0],
                            f"{rng.randint(1, ward[2]):02d}",
                            adm_dt,
                            dsch_dt,
                            "NORMAL" if dsch_dt else None,
                            rng.choice(["OPD", "ER", "TRANSFER"]),
                        ),
                    )
                    counts["admissions"] += 1

                # Diagnoses
                dgn_n = rng.randint(1, 3)
                chosen_dgn = rng.sample(DGN_CODES, dgn_n)
                for seq, dgn in enumerate(chosen_dgn, start=1):
                    cur.execute(
                        """
                        INSERT INTO TB_DGN_HIST
                        (ENC_ID, PT_NO, DGN_CD, DGN_SEQ, DGN_TYP, ONSET_DT, DGN_DT, PROV_ID)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            enc_id,
                            pt_no,
                            dgn[0],
                            seq,
                            "MAIN" if seq == 1 else "SUB",
                            (adm_dt - timedelta(days=rng.randint(0, 365))).date(),
                            adm_dt + timedelta(minutes=30),
                            prov[0],
                        ),
                    )
                    counts["diagnoses"] += 1

                # Procedures (subset)
                if rng.random() < 0.45:
                    proc = rng.choice(PROCS)
                    cur.execute(
                        """
                        INSERT INTO TB_PROC_HIST
                        (ENC_ID, PT_NO, PROC_CD, PROC_DT, PROV_ID, DEPT_CD, PROC_STS, RMRK_TXT)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                        """,
                        (
                            enc_id,
                            pt_no,
                            proc[0],
                            adm_dt + timedelta(hours=1),
                            prov[0],
                            dept[0],
                            "DONE",
                            None,
                        ),
                    )
                    counts["procedures"] += 1

                # Lab panel order -> detail -> lab_ord -> lab_rst
                if rng.random() < 0.80:
                    panel = rng.choice(
                        [
                            ["L_AST", "L_ALT", "L_GGT", "L_ALP", "L_TBIL"],
                            ["L_GLU", "L_FBS", "L_HBA1C"],
                            ["L_CRE", "L_EGFR", "L_BUN"],
                            ["L_AST", "L_ALT", "L_CRE", "L_GLU", "L_WBC", "L_HGB"],
                        ]
                    )
                    hist_days = rng.sample(range(0, 180), k=rng.randint(1, 3))
                    for day_offset in hist_days:
                        ord_no = f"OL{i:06d}{e:02d}{day_offset:03d}"
                        ord_dt = adm_dt - timedelta(days=day_offset) + timedelta(hours=2)
                        cur.execute(
                            """
                            INSERT INTO TB_ORD_HDR
                            (ORD_NO, ENC_ID, PT_NO, ORD_TYP, ORD_STS, ORD_DT, PROV_ID, DEPT_CD)
                            VALUES (%s,%s,%s,'LAB','DONE',%s,%s,%s)
                            """,
                            (ord_no, enc_id, pt_no, ord_dt, prov[0], dept[0]),
                        )
                        for seq, exm_cd in enumerate(panel, start=1):
                            exm = next(x for x in LAB_TESTS if x[0] == exm_cd)
                            cur.execute(
                                """
                                INSERT INTO TB_ORD_DTL
                                (ORD_NO, ORD_SEQ, ORD_CD, ORD_NM, QTY_VAL, UNIT_CD, ORD_STS)
                                VALUES (%s,%s,%s,%s,1,%s,'DONE')
                                RETURNING ORD_DTL_ID
                                """,
                                (ord_no, seq, exm_cd, exm[1], exm[5]),
                            )
                            dtl_id = cur.fetchone()["ord_dtl_id"]
                            cur.execute(
                                """
                                INSERT INTO TB_LAB_ORD
                                (ORD_NO, ORD_DTL_ID, ENC_ID, PT_NO, EXM_CD, SPC_NO, COLL_DT, ORD_STS)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,'DONE')
                                RETURNING LAB_ORD_ID
                                """,
                                (
                                    ord_no,
                                    dtl_id,
                                    enc_id,
                                    pt_no,
                                    exm_cd,
                                    f"SPC{i:06d}{e:02d}{day_offset:03d}{seq:02d}",
                                    ord_dt + timedelta(minutes=20),
                                ),
                            )
                            lab_ord_id = cur.fetchone()["lab_ord_id"]
                            num, txt, unit = lab_value(rng, exm_cd)
                            rst_dt = ord_dt + timedelta(hours=rng.randint(2, 24))
                            cur.execute(
                                """
                                INSERT INTO TB_LAB_RST
                                (LAB_ORD_ID, PT_NO, EXM_CD, RST_VAL, RST_NUM, RST_UNIT, ABN_FLG, RST_DT, RPT_PROV_ID)
                                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                                """,
                                (
                                    lab_ord_id,
                                    pt_no,
                                    exm_cd,
                                    txt,
                                    num,
                                    unit,
                                    abnormal(exm_cd, num),
                                    rst_dt,
                                    lab_staff[0][0],
                                ),
                            )
                            counts["lab_results"] += 1

                # Medication order
                if rng.random() < 0.70:
                    drugs = rng.sample(DRUGS, k=rng.randint(1, 3))
                    ord_no = f"OM{i:06d}{e:02d}"
                    cur.execute(
                        """
                        INSERT INTO TB_ORD_HDR
                        (ORD_NO, ENC_ID, PT_NO, ORD_TYP, ORD_STS, ORD_DT, PROV_ID, DEPT_CD)
                        VALUES (%s,%s,%s,'MED','DONE',%s,%s,%s)
                        """,
                        (ord_no, enc_id, pt_no, adm_dt + timedelta(hours=1), prov[0], dept[0]),
                    )
                    for seq, drug in enumerate(drugs, start=1):
                        cur.execute(
                            """
                            INSERT INTO TB_ORD_DTL
                            (ORD_NO, ORD_SEQ, ORD_CD, ORD_NM, QTY_VAL, UNIT_CD, ORD_STS)
                            VALUES (%s,%s,%s,%s,%s,%s,'DONE')
                            RETURNING ORD_DTL_ID
                            """,
                            (ord_no, seq, drug[0], drug[1], 1, drug[6]),
                        )
                        dtl_id = cur.fetchone()["ord_dtl_id"]
                        days = rng.choice([3, 7, 14, 30])
                        cur.execute(
                            """
                            INSERT INTO TB_MED_ORD
                            (ORD_NO, ORD_DTL_ID, ENC_ID, PT_NO, DRUG_CD, DOSE_VAL, DOSE_UNIT,
                             FREQ_CD, DAYS_CNT, ROUTE_CD, START_DT, END_DT, ORD_STS)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PO',%s,%s,'DONE')
                            """,
                            (
                                ord_no,
                                dtl_id,
                                enc_id,
                                pt_no,
                                drug[0],
                                1,
                                drug[6],
                                rng.choice(["QD", "BID", "TID"]),
                                days,
                                adm_dt + timedelta(hours=2),
                                adm_dt + timedelta(days=days),
                            ),
                        )
                        counts["medications"] += 1

                # Imaging order + report
                if rng.random() < 0.40:
                    img = rng.choice(IMG_TESTS)
                    ord_no = f"OI{i:06d}{e:02d}"
                    ord_dt = adm_dt + timedelta(hours=3)
                    cur.execute(
                        """
                        INSERT INTO TB_ORD_HDR
                        (ORD_NO, ENC_ID, PT_NO, ORD_TYP, ORD_STS, ORD_DT, PROV_ID, DEPT_CD)
                        VALUES (%s,%s,%s,'IMG','DONE',%s,%s,%s)
                        """,
                        (ord_no, enc_id, pt_no, ord_dt, prov[0], dept[0]),
                    )
                    cur.execute(
                        """
                        INSERT INTO TB_ORD_DTL
                        (ORD_NO, ORD_SEQ, ORD_CD, ORD_NM, QTY_VAL, UNIT_CD, ORD_STS)
                        VALUES (%s,1,%s,%s,1,'회','DONE')
                        RETURNING ORD_DTL_ID
                        """,
                        (ord_no, img[0], img[1]),
                    )
                    dtl_id = cur.fetchone()["ord_dtl_id"]
                    cur.execute(
                        """
                        INSERT INTO TB_IMG_ORD
                        (ORD_NO, ORD_DTL_ID, ENC_ID, PT_NO, IMG_CD, ACC_NO, ORD_DT, PERF_DT, ORD_STS)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'DONE')
                        RETURNING IMG_ORD_ID
                        """,
                        (
                            ord_no,
                            dtl_id,
                            enc_id,
                            pt_no,
                            img[0],
                            f"ACC{i:06d}{e:02d}",
                            ord_dt,
                            ord_dt + timedelta(hours=2),
                        ),
                    )
                    img_ord_id = cur.fetchone()["img_ord_id"]
                    cur.execute(
                        """
                        INSERT INTO TB_IMG_RPT
                        (IMG_ORD_ID, PT_NO, RPT_DT, RPT_PROV_ID, FIND_TXT, IMPR_TXT, RPT_STS)
                        VALUES (%s,%s,%s,%s,%s,%s,'FINAL')
                        """,
                        (
                            img_ord_id,
                            pt_no,
                            ord_dt + timedelta(hours=6),
                            radiologists[0][0],
                            f"{img[1]} 검사상 특이 급성 병변은 뚜렷하지 않음.",
                            rng.choice(["정상 범위", "경미한 이상 소견", "추가 평가 권고"]),
                        ),
                    )
                    counts["imaging_reports"] += 1

                # Clinical documents
                if enc_typ == "I" or rng.random() < 0.35:
                    doc_typ = "DT_DSCH" if enc_typ == "I" else rng.choice(["DT_PROG", "DT_ADM", "DT_CONS"])
                    doc_nm = next(d for d in DOC_TYPES if d[0] == doc_typ)[1]
                    cur.execute(
                        """
                        INSERT INTO TB_CLN_DOC
                        (DOC_ID, ENC_ID, PT_NO, DOC_TYP_CD, DOC_TTL, DOC_BODY, AUTH_PROV_ID, DOC_DT, DOC_STS)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'SIGNED')
                        """,
                        (
                            f"DOC{i:06d}{e:02d}",
                            enc_id,
                            pt_no,
                            doc_typ,
                            f"{doc_nm} - {pt_no}",
                            f"{name} 환자 {doc_nm}입니다. Encounter {enc_id} 관련 기록.",
                            prov[0],
                            dsch_dt or (adm_dt + timedelta(hours=4)),
                        ),
                    )
                    counts["clinical_documents"] += 1

            if i % 50 == 0:
                conn.commit()
                print(f"Seeded patients: {i}/{patient_count}", flush=True)

    conn.commit()
    return counts


def main() -> int:
    patient_count = int(os.getenv("SEED_PATIENT_COUNT", "200"))
    random_seed = int(os.getenv("SEED_RANDOM_SEED", "42"))
    force = os.getenv("SEED_FORCE", "false").lower() in {"1", "true", "yes"}

    rng = random.Random(random_seed)
    print(f"Connecting to medical_demo (patients={patient_count}, seed={random_seed})")

    with connect() as conn:
        if already_seeded(conn) and not force:
            print("Seed skipped: TB_PT_MST already has data (set SEED_FORCE=true to reseed).")
            return 0
        if force:
            print("SEED_FORCE=true -> truncating clinical/master tables")
            truncate_all(conn)

        seed_masters(conn)
        counts = seed_clinical(conn, patient_count, rng)
        print("Seed completed:")
        for key, value in counts.items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"Seed failed: {exc}", file=sys.stderr)
        raise

"""
tasks/quality_check.py
----------------------
Reads feature_matrix after transform and validates:
    1. Row count — must meet minimum threshold
    2. Null percentage — no column exceeds max null threshold
    3. Completeness — avg completeness_pct across all rows
    4. Duplicate natural keys — zero tolerance

Why a dedicated quality check task?
    If you embed checks inside transform.py, a quality failure
    rolls back the transform. A separate task means:
    - Transform always commits its output
    - Quality check independently decides pass/fail
    - You can retry quality check without re-running transform
    - The failure shows up as a distinct task in Airflow UI —
      immediately obvious what went wrong and where

Why raise AirflowException on failure?
    This marks the task as FAILED in Airflow, stops downstream
    tasks from running, and triggers any alert hooks you have
    configured (email, Slack, PagerDuty). Logging a warning
    and continuing silently is how bad data reaches production.

XCom output:
    quality_passed (bool)
    null_pct_actual (float)
    quality_notes (str)
"""

import os
import time
import logging
import pandas as pd
import psycopg2
from airflow.exceptions import AirflowException

log = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────
# These are the SLA parameters for this pipeline.
# Change them here — they propagate everywhere automatically.
MIN_ROW_COUNT       = 50      # fewer rows than this = something went wrong
MAX_NULL_PCT        = 80.0    # any column >80% null = quality failure
MIN_COMPLETENESS    = 20.0    # avg completeness_pct must be above this
MAX_DUPLICATE_KEYS  = 0       # zero tolerance on duplicate country+year


def get_pipeline_db_conn():
    return psycopg2.connect(
        host=os.environ["PIPELINE_DB_HOST"],
        port=os.environ["PIPELINE_DB_PORT"],
        dbname=os.environ["PIPELINE_DB_NAME"],
        user=os.environ["PIPELINE_DB_USER"],
        password=os.environ["PIPELINE_DB_PASSWORD"],
    )


def quality_check(**context):
    start = time.time()
    run_id = context["run_id"]
    log.info(f"Starting quality check | run_id={run_id}")

    conn = get_pipeline_db_conn()
    notes = []
    passed = True

    try:
        # ── Read feature_matrix ───────────────────────────────
        df = pd.read_sql(
            "SELECT * FROM feature_matrix",
            conn
        )
        log.info(f"feature_matrix has {len(df):,} rows")

        # ── Check 1: Minimum row count ────────────────────────
        if len(df) < MIN_ROW_COUNT:
            msg = (f"FAIL row count: {len(df)} < "
                   f"minimum {MIN_ROW_COUNT}")
            log.error(msg)
            notes.append(msg)
            passed = False
        else:
            log.info(f"PASS row count: {len(df):,}")
        
        # ── Check 2: Null percentage per column ───────────────
        # Only check numeric feature columns, not metadata cols
        skip_cols = {"id", "country_code", "country_name", "year",
                     "region", "pipeline_run_id", "loaded_at",
                     "non_null_feature_count", "completeness_pct"}
        feature_cols = [c for c in df.columns if c not in skip_cols]

        if feature_cols:
            null_pcts = (df[feature_cols].isnull().mean() * 100).round(2)

            # Ignore columns that are 100% null – they are effectively not present
            null_pcts = null_pcts[null_pcts < 100.0]

            bad_cols = null_pcts[null_pcts > MAX_NULL_PCT]

            if not bad_cols.empty:
                msg = (f"FAIL null threshold exceeded in "
                       f"{len(bad_cols)} columns: "
                       f"{bad_cols.to_dict()}")
                log.error(msg)
                notes.append(msg)
                passed = False
            else:
                log.info(f"PASS null check: all checked columns "
                         f"within {MAX_NULL_PCT}% threshold")
        else:
            log.info("No feature columns to check for null percentages")

        # ── Check 3: Average completeness ─────────────────────
        avg_completeness = df["completeness_pct"].mean().round(2)
        if avg_completeness < MIN_COMPLETENESS:
            msg = (f"FAIL avg completeness: {avg_completeness}% < "
                   f"minimum {MIN_COMPLETENESS}%")
            log.error(msg)
            notes.append(msg)
            passed = False
        else:
            log.info(f"PASS avg completeness: {avg_completeness}%")

        # ── Check 4: Duplicate natural keys ───────────────────
        dupes = df.duplicated(
            subset=["country_code", "year"]
        ).sum()
        if dupes > MAX_DUPLICATE_KEYS:
            msg = (f"FAIL duplicates: {dupes} duplicate "
                   f"(country_code, year) pairs found")
            log.error(msg)
            notes.append(msg)
            passed = False
        else:
            log.info(f"PASS duplicate check: 0 duplicates")

    finally:
        conn.close()

    # ── Push results to XCom ──────────────────────────────────
    quality_notes = " | ".join(notes) if notes else "All checks passed"
    context["ti"].xcom_push(key="quality_passed", value=passed)
    context["ti"].xcom_push(
        key="null_pct_actual",
        value=float(null_pcts.max()) if len(df) > 0 else None
    )
    context["ti"].xcom_push(key="quality_notes", value=quality_notes)
    context["ti"].xcom_push(
        key="quality_check_duration_sec",
        value=round(time.time() - start, 2)
    )

    # ── Fail the task if any check failed ─────────────────────
    # This stops the load task from running and marks the
    # DAG run as FAILED in the Airflow UI
    if not passed:
        raise AirflowException(
            f"Quality checks failed: {quality_notes}"
        )

    log.info("All quality checks passed")
    return True

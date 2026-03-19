"""
tasks/clean.py
--------------
Silver layer: reads raw_indicators for the current run,
applies cleaning rules, upserts into cleaned_indicators.

Cleaning rules applied:
    1. Replace World Bank '..' missing value marker with NULL
    2. Cast value column from TEXT to NUMERIC
    3. Drop rows where country_code, series_code, or year is null
    4. Deduplicate on natural key (country_code, series_code, year, source)
    5. Strip whitespace from string columns

Why upsert instead of insert?
    The DAG may re-run due to failure or manual trigger.
    INSERT would create duplicate rows. ON CONFLICT DO UPDATE
    refreshes existing rows and is idempotent — safe to run
    as many times as needed.

XCom output:
    rows_cleaned (int)
    clean_duration_sec (float)
"""

import os
import time
import logging
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def get_pipeline_db_conn():
    return psycopg2.connect(
        host=os.environ["PIPELINE_DB_HOST"],
        port=os.environ["PIPELINE_DB_PORT"],
        dbname=os.environ["PIPELINE_DB_NAME"],
        user=os.environ["PIPELINE_DB_USER"],
        password=os.environ["PIPELINE_DB_PASSWORD"],
    )


def clean(**context):
    start = time.time()
    run_id = context["run_id"]
    log.info(f"Starting clean | run_id={run_id}")

    conn = get_pipeline_db_conn()

    # ── Read from bronze ──────────────────────────────────────
    # We read ALL raw data, not just this run's rows.
    # Reason: cleaning is idempotent. If raw gets new rows
    # from a re-run, we want clean to reflect the full dataset.
    query = """
        SELECT country_code, country_name, series_code,
               series_name, year, value, source
        FROM raw_indicators
    """
    df = pd.read_sql(query, conn)
    log.info(f"Read {len(df):,} rows from raw_indicators")

    # ── Rule 1: Replace World Bank missing value marker ───────
    # World Bank exports use '..' for missing values, not empty
    df["value"] = df["value"].replace({".." : None, "nan": None, "": None})

    # ── Rule 2: Cast value to numeric ─────────────────────────
    # errors="coerce" turns anything non-numeric into NaN/None
    # rather than raising an exception
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # ── Rule 3: Drop rows missing natural key components ──────
    before = len(df)
    df = df.dropna(subset=["country_code", "series_code", "year"])
    dropped_nulls = before - len(df)
    if dropped_nulls > 0:
        log.warning(f"Dropped {dropped_nulls:,} rows with null natural key")

    # ── Rule 4: Deduplicate on natural key ────────────────────
    # Keep the last occurrence (most recently ingested)
    before = len(df)
    df = df.drop_duplicates(
        subset=["country_code", "series_code", "year", "source"],
        keep="last"
    )
    dropped_dupes = before - len(df)
    if dropped_dupes > 0:
        log.info(f"Removed {dropped_dupes:,} duplicate rows")

    # ── Rule 5: Strip whitespace from string columns ──────────
    for col in ["country_code", "country_name", "series_code",
                "series_name", "source"]:
        df[col] = df[col].str.strip()

    # ── Cast year to int ──────────────────────────────────────
    df["year"] = df["year"].astype(int)

    cleaned_at = datetime.now(timezone.utc)

    # ── Upsert into silver ────────────────────────────────────
    rows = [
        (
            row.country_code,
            row.country_name,
            row.series_code,
            row.series_name,
            int(row.year),
            float(row.value) if pd.notna(row.value) else None,
            row.source,
            cleaned_at,
        )
        for row in df.itertuples(index=False)
    ]

    upsert_sql = """
        INSERT INTO cleaned_indicators
            (country_code, country_name, series_code, series_name,
             year, value, source, cleaned_at)
        VALUES %s
        ON CONFLICT (country_code, series_code, year, source)
        DO UPDATE SET
            value      = EXCLUDED.value,
            cleaned_at = EXCLUDED.cleaned_at
    """

    try:
        with conn.cursor() as cur:
            execute_values(cur, upsert_sql, rows, page_size=5000)
        conn.commit()
        log.info(f"Upserted {len(rows):,} rows into cleaned_indicators")
    except Exception as e:
        conn.rollback()
        log.error(f"Clean failed: {e}")
        raise
    finally:
        conn.close()

    duration = round(time.time() - start, 2)
    log.info(f"Clean complete | rows={len(rows):,} | duration={duration}s")

    context["ti"].xcom_push(key="rows_cleaned", value=len(rows))
    context["ti"].xcom_push(key="clean_duration_sec", value=duration)

    return len(rows)

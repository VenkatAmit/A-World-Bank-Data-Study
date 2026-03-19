import os
import time
import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

CHUNK_SIZE = 100_000


def get_pipeline_db_conn():
    return psycopg2.connect(
        host=os.environ["PIPELINE_DB_HOST"],
        port=os.environ["PIPELINE_DB_PORT"],
        dbname=os.environ["PIPELINE_DB_NAME"],
        user=os.environ["PIPELINE_DB_USER"],
        password=os.environ["PIPELINE_DB_PASSWORD"],
    )


def _clean_chunk(df):
    for col in ["country_code", "country_name", "series_code", "series_name", "source"]:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip()
    df["value"] = df["value"].replace({"..": None, "nan": None, "": None})
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["country_code", "series_code", "year"])
    df = df.drop_duplicates(
        subset=["country_code", "series_code", "year", "source"],
        keep="last",
    )
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year"])
    df["year"] = df["year"].astype(int)
    return df


def clean(**context):
    start = time.time()
    run_id = context["run_id"]
    log.info(f"Starting clean | run_id={run_id}")

    conn = get_pipeline_db_conn()
    total_rows = 0
    cleaned_at = datetime.now(timezone.utc)

    query = """
        SELECT country_code, country_name, series_code,
               series_name, year, value, source
        FROM raw_indicators
    """

    try:
        with conn, conn.cursor() as cur:
            for chunk in pd.read_sql(query, conn, chunksize=CHUNK_SIZE):
                log.info(f"Read chunk with {len(chunk):,} rows from raw_indicators")
                df = _clean_chunk(chunk)
                if df.empty:
                    continue
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
                execute_values(cur, """
                    INSERT INTO cleaned_indicators
                        (country_code, country_name, series_code, series_name,
                         year, value, source, cleaned_at)
                    VALUES %s
                    ON CONFLICT (country_code, series_code, year, source)
                    DO UPDATE SET
                        value      = EXCLUDED.value,
                        cleaned_at = EXCLUDED.cleaned_at
                """, rows, page_size=5_000)
                total_rows += len(rows)
                log.info(f"Upserted {len(rows):,} rows (cumulative {total_rows:,})")
    except Exception as e:
        log.error(f"Clean failed: {e}")
        raise
    finally:
        conn.close()

    duration = round(time.time() - start, 2)
    log.info(f"Clean complete | rows={total_rows:,} | duration={duration}s")
    ti = context["ti"]
    ti.xcom_push(key="rows_cleaned", value=total_rows)
    ti.xcom_push(key="clean_duration_sec", value=duration)
    return total_rows

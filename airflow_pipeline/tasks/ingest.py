"""
tasks/ingest.py
---------------
Bronze layer: reads the source CSV and loads raw rows
into raw_indicators. Append-only — no updates, no deletes.
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


def ingest(**context):
    start = time.time()
    run_id = context["run_id"]
    data_path = os.environ["DATAPATH"]

    log.info(f"Starting ingest | run_id={run_id} | source={data_path}")

    df = pd.read_csv(data_path, low_memory=False)
    log.info(f"CSV loaded: {df.shape[0]:,} rows x {df.shape[1]} columns")

    required = {"Country Name", "Country Code", "Series Name",
                "Series Code", "Year", "Value", "Source", "Indicator Category"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"CSV missing required columns: {missing}")

    df = df[["Country Name", "Country Code", "Series Name",
             "Series Code", "Year", "Value", "Source", "Indicator Category"]].copy()
    df.columns = ["country_name", "country_code", "series_name",
                  "series_code", "year", "value", "source", "indicator_category"]

    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.dropna(subset=["year", "country_code", "series_code"])
    df["year"] = df["year"].astype(int)
    df["value"] = df["value"].astype(str).replace("nan", None)

    ingested_at = datetime.now(timezone.utc)

    rows = [
        (
            row.country_code,
            row.country_name,
            row.series_code,
            row.series_name,
            int(row.year),
            row.value if row.value != "None" else None,
            row.source,
            str(row.indicator_category) if pd.notna(row.indicator_category) else None,
            ingested_at,
        )
        for row in df.itertuples(index=False)
    ]

    insert_sql = """
        INSERT INTO raw_indicators
            (country_code, country_name, series_code, series_name,
             year, value, source, indicator_category, ingested_at)
        VALUES %s
    """

    conn = get_pipeline_db_conn()
    try:
        with conn.cursor() as cur:
            execute_values(cur, insert_sql, rows, page_size=5000)
        conn.commit()
        log.info(f"Inserted {len(rows):,} rows into raw_indicators")
    except Exception as e:
        conn.rollback()
        log.error(f"Ingest failed: {e}")
        raise
    finally:
        conn.close()

    duration = round(time.time() - start, 2)
    log.info(f"Ingest complete | rows={len(rows):,} | duration={duration}s")

    context["ti"].xcom_push(key="rows_ingested", value=len(rows))
    context["ti"].xcom_push(key="ingest_duration_sec", value=duration)

    return len(rows)

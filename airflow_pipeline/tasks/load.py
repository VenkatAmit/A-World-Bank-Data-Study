"""
tasks/load.py
-------------
Final task: writes a row to pipeline_run_log summarising
the entire pipeline run — row counts, timing, quality results.

Why is "load" just logging here?
    The actual data loading happened in transform.py — the
    feature_matrix table is already populated and committed
    before this task runs. This task's job is observability:
    record what happened, how long it took, and whether
    quality checks passed. This is the table you query when
    an interviewer asks "how do you monitor your pipelines?"

    In a production pipeline this task would also:
    - Send a Slack/email notification
    - Update a data catalog (Datahub, Amundsen)
    - Trigger downstream consumers
    - Update a dashboard with freshness timestamps

XCom inputs (pulled from upstream tasks):
    rows_ingested           from ingest
    ingest_duration_sec     from ingest
    rows_cleaned            from clean
    clean_duration_sec      from clean
    rows_transformed        from transform
    transform_duration_sec  from transform
    quality_passed          from quality_check
    null_pct_actual         from quality_check
    quality_notes           from quality_check
"""

import os
import time
import logging
import psycopg2
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


def pull(ti, task_id, key):
    """
    Safely pull an XCom value. Returns None if not found
    rather than raising — load should always succeed even
    if an upstream task didn't push a value.
    """
    try:
        return ti.xcom_pull(task_ids=task_id, key=key)
    except Exception:
        return None


def load(**context):
    start = time.time()
    run_id = context["run_id"]
    dag_id = context["dag"].dag_id
    run_started_at = context["data_interval_start"]
    ti = context["ti"]

    log.info(f"Starting load (run log) | run_id={run_id}")

    # ── Pull XCom values from all upstream tasks ──────────────
    rows_ingested           = pull(ti, "ingest",         "rows_ingested")
    ingest_duration         = pull(ti, "ingest",         "ingest_duration_sec")
    rows_cleaned            = pull(ti, "clean",          "rows_cleaned")
    clean_duration          = pull(ti, "clean",          "clean_duration_sec")
    rows_transformed        = pull(ti, "transform",      "rows_transformed")
    transform_duration      = pull(ti, "transform",      "transform_duration_sec")
    quality_passed          = pull(ti, "quality_check",  "quality_passed")
    null_pct_actual         = pull(ti, "quality_check",  "null_pct_actual")
    quality_notes           = pull(ti, "quality_check",  "quality_notes")

    run_completed_at = datetime.now(timezone.utc)
    total_duration = round(time.time() - start, 2)

    # ── Summarise to log ──────────────────────────────────────
    log.info(
        f"Pipeline run summary | "
        f"ingested={rows_ingested} | "
        f"cleaned={rows_cleaned} | "
        f"transformed={rows_transformed} | "
        f"quality={'PASS' if quality_passed else 'FAIL'} | "
        f"notes={quality_notes}"
    )

    # ── Write to pipeline_run_log ─────────────────────────────
    insert_sql = """
        INSERT INTO pipeline_run_log (
            pipeline_run_id, dag_id,
            run_started_at, run_completed_at,
            rows_ingested, rows_cleaned, rows_loaded,
            quality_passed, null_pct_threshold,
            null_pct_actual, quality_notes,
            ingest_duration_sec, clean_duration_sec,
            transform_duration_sec, load_duration_sec,
            total_duration_sec
        )
        VALUES (
            %(run_id)s, %(dag_id)s,
            %(run_started_at)s, %(run_completed_at)s,
            %(rows_ingested)s, %(rows_cleaned)s, %(rows_loaded)s,
            %(quality_passed)s, %(null_pct_threshold)s,
            %(null_pct_actual)s, %(quality_notes)s,
            %(ingest_duration)s, %(clean_duration)s,
            %(transform_duration)s, %(load_duration)s,
            %(total_duration)s
        )
        ON CONFLICT (pipeline_run_id)
        DO UPDATE SET
            run_completed_at        = EXCLUDED.run_completed_at,
            rows_ingested           = EXCLUDED.rows_ingested,
            rows_cleaned            = EXCLUDED.rows_cleaned,
            rows_loaded             = EXCLUDED.rows_loaded,
            quality_passed          = EXCLUDED.quality_passed,
            null_pct_actual         = EXCLUDED.null_pct_actual,
            quality_notes           = EXCLUDED.quality_notes,
            ingest_duration_sec     = EXCLUDED.ingest_duration_sec,
            clean_duration_sec      = EXCLUDED.clean_duration_sec,
            transform_duration_sec  = EXCLUDED.transform_duration_sec,
            load_duration_sec       = EXCLUDED.load_duration_sec,
            total_duration_sec      = EXCLUDED.total_duration_sec
    """

    conn = get_pipeline_db_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(insert_sql, {
                "run_id":               run_id,
                "dag_id":               dag_id,
                "run_started_at":       run_started_at,
                "run_completed_at":     run_completed_at,
                "rows_ingested":        rows_ingested,
                "rows_cleaned":         rows_cleaned,
                "rows_loaded":          rows_transformed,
                "quality_passed":       quality_passed,
                "null_pct_threshold":   80.0,
                "null_pct_actual":      null_pct_actual,
                "quality_notes":        quality_notes,
                "ingest_duration":      ingest_duration,
                "clean_duration":       clean_duration,
                "transform_duration":   transform_duration,
                "load_duration":        round(time.time() - start, 2),
                "total_duration":       total_duration,
            })
        conn.commit()
        log.info("Pipeline run log written successfully")
    except Exception as e:
        conn.rollback()
        log.error(f"Failed to write run log: {e}")
        raise
    finally:
        conn.close()

    return run_id

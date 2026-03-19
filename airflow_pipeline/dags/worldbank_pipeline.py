"""
dags/worldbank_pipeline.py
--------------------------
World Bank Data Pipeline — medallion architecture
Bronze (raw) → Silver (cleaned) → Gold (feature_matrix)

DAG design decisions:
    - schedule_interval="@daily" with catchup=False:
      runs once per day, does not backfill historical runs.
      Change to catchup=True if you want to replay past dates.

    - max_active_runs=1:
      prevents two runs of this DAG from executing concurrently.
      Without this, two simultaneous runs could conflict on
      the upsert natural keys.

    - provide_context=True on every PythonOperator:
      injects the Airflow task context (run_id, ti, dag, etc.)
      into each task function. Required for XCom push/pull.

    - Task dependencies set with >> operator:
      ingest >> clean >> transform >> quality_check >> load
      Each task only starts if the previous one succeeded.
      If quality_check raises AirflowException, load never runs.

Talking points for interviews:
    - XCom used to pass row counts and timing between tasks
      without re-querying the database
    - Upsert pattern (ON CONFLICT DO UPDATE) makes every task
      idempotent — safe to re-run without duplicating data
    - quality_check raises AirflowException on failure —
      stops the pipeline before bad data reaches the gold layer
    - pipeline_run_log table gives full observability:
      row counts, timing, quality results per run
    - LocalExecutor chosen over CeleryExecutor — simpler setup,
      same DAG code works with either executor
"""

from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
import sys
import os

# ── Make tasks/ importable inside the container ───────────────
# Airflow mounts dags/ and tasks/ separately. Adding tasks/
# to sys.path lets us import from tasks/ as a package.
sys.path.insert(0, "/opt/airflow/tasks")

from ingest        import ingest
from clean         import clean
from transform     import transform
from quality_check import quality_check
from load          import load

# ── Default args — apply to every task in the DAG ─────────────
default_args = {
    "owner":            "venkat-amit",
    "depends_on_past":  False,
    "email_on_failure": False,
    "email_on_retry":   False,
    "retries":          1,
    "retry_delay":      timedelta(minutes=5),
}

# ── DAG definition ────────────────────────────────────────────
with DAG(
    dag_id="worldbank_pipeline",
    description=(
        "World Bank indicator pipeline: "
        "CSV → raw_indicators → cleaned_indicators → feature_matrix"
    ),
    default_args=default_args,
    start_date=datetime(2025, 1, 1),
    schedule_interval="@daily",
    catchup=False,
    max_active_runs=1,
    tags=["worldbank", "medallion", "portfolio"],
) as dag:

    # ── Task 1: Ingest ────────────────────────────────────────
    # Reads source CSV, loads into bronze (raw_indicators).
    # Append-only. Fails fast if required columns are missing.
    t_ingest = PythonOperator(
        task_id="ingest",
        python_callable=ingest,
        provide_context=True,
    )

    # ── Task 2: Clean ─────────────────────────────────────────
    # Reads bronze, applies cleaning rules, upserts to silver.
    # Handles World Bank '..' null marker, casts types, dedupes.
    t_clean = PythonOperator(
        task_id="clean",
        python_callable=clean,
        provide_context=True,
    )

    # ── Task 3: Transform ─────────────────────────────────────
    # Reads silver, pivots long→wide, builds derived features,
    # computes completeness metrics, upserts to gold.
    t_transform = PythonOperator(
        task_id="transform",
        python_callable=transform,
        provide_context=True,
    )

    # ── Task 4: Quality check ─────────────────────────────────
    # Validates gold layer: row count, null %, completeness,
    # duplicate keys. Raises AirflowException on failure —
    # stops the load task and marks the run as FAILED.
    t_quality_check = PythonOperator(
        task_id="quality_check",
        python_callable=quality_check,
        provide_context=True,
    )

    # ── Task 5: Load (run log) ────────────────────────────────
    # Pulls XCom values from all upstream tasks and writes
    # a summary row to pipeline_run_log. Always the last task.
    t_load = PythonOperator(
        task_id="load",
        python_callable=load,
        provide_context=True,
    )

    # ── Task dependencies ─────────────────────────────────────
    # Linear pipeline: each task waits for the previous to
    # succeed before starting. >> is Airflow's dependency operator.
    t_ingest >> t_clean >> t_transform >> t_quality_check >> t_load

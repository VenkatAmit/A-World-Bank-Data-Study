"""
tasks/transform.py
------------------
Gold layer: pivots cleaned_indicators from long to wide format,
builds derived ratio features, computes completeness metrics,
upserts into feature_matrix.

Why pivot here and not in clean?
    Clean operates on long-format data (one row per indicator
    per country per year) — that's the right shape for cleaning
    because each row is independently validatable.
    Wide format only makes sense once the data is clean,
    because pivoting dirty data propagates nulls and type
    errors across many columns simultaneously.

XCom output:
    rows_transformed (int)
    transform_duration_sec (float)
"""

import os
import time
import logging
import numpy as np
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime, timezone

log = logging.getLogger(__name__)

# ── Indicator → column name mapping ──────────────────────────
# Maps World Bank series codes to readable column names.
# Only these indicators make it into the gold table.
# Everything else is available in silver for ad-hoc queries.
INDICATOR_MAP = {
    "NY.GDP.MKTP.KD.ZG": "gdp_growth_pct",
    "NY.GDP.MKTP.CD":     "gdp_current_usd",
    "NY.GNP.PCAP.CD":     "gni_per_capita_usd",
    "FP.CPI.TOTL.ZG":     "inflation_pct",
    "BN.CAB.XOKA.GD.ZS":  "current_account_pct_gdp",
    "BX.KLT.DINV.WD.GD.ZS": "fdi_net_inflows_pct_gdp",
    "SL.UEM.TOTL.ZS":     "unemployment_pct",
    "SI.POV.GINI":         "gini_index",
    "SP.DYN.LE00.IN":      "life_expectancy_years",
    "SE.PRM.ENRR":         "school_enrollment_primary",
    "SI.POV.DDAY":         "poverty_headcount_ratio",
    "FM.LBL.BMNY.GD.ZS":  "broad_money_pct_gdp",
    "FB.BNK.CAPA.ZS":     "bank_capital_to_assets_pct",
    "FS.AST.DCFS.GD.ZS":  "domestic_credit_pct_gdp",
    "EN.ATM.CO2E.KT":     "co2_emissions_kt",
    "EG.FEC.RNEW.ZS":     "renewable_energy_pct",
    "SP.POP.TOTL":        "population_total",  # used for derived features
    "GC.DOD.TOTL.GD.ZS":  "public_debt_pct_gdp",  # used for derived features
}


def get_pipeline_db_conn():
    return psycopg2.connect(
        host=os.environ["PIPELINE_DB_HOST"],
        port=os.environ["PIPELINE_DB_PORT"],
        dbname=os.environ["PIPELINE_DB_NAME"],
        user=os.environ["PIPELINE_DB_USER"],
        password=os.environ["PIPELINE_DB_PASSWORD"],
    )


def transform(**context):
    start = time.time()
    run_id = context["run_id"]
    log.info(f"Starting transform | run_id={run_id}")

    conn = get_pipeline_db_conn()

    # ── Read silver layer ─────────────────────────────────────
    query = """
        SELECT country_code, country_name, series_code, year, value
        FROM cleaned_indicators
        WHERE series_code = ANY(%(codes)s)
    """
    df = pd.read_sql(
        query,
        conn,
        params={"codes": list(INDICATOR_MAP.keys())}
    )
    log.info(f"Read {len(df):,} rows from cleaned_indicators")

    if df.empty:
        log.warning("No rows matched indicator map — check series codes")
        return 0

    # ── Pivot long → wide ─────────────────────────────────────
    # Each series_code becomes its own column.
    # aggfunc="mean" handles the rare case where one country-year
    # has multiple values for the same indicator (takes average).
    wide = df.pivot_table(
        index=["country_code", "country_name", "year"],
        columns="series_code",
        values="value",
        aggfunc="mean"
    ).reset_index()

    # ── Rename series codes to readable column names ───────────
    wide.rename(columns=INDICATOR_MAP, inplace=True)
    log.info(f"Pivoted to wide format: {wide.shape}")

    # ── Derived ratio features ────────────────────────────────
    # GDP per capita: total GDP / population
    if "gdp_current_usd" in wide.columns and "population_total" in wide.columns:
        wide["gdp_per_capita_usd"] = (
            wide["gdp_current_usd"] / wide["population_total"].replace(0, np.nan)
        ).round(2)

    # Debt-to-GDP: already a % in World Bank data but we compute
    # an absolute ratio for modelling purposes
    if "public_debt_pct_gdp" in wide.columns and "gdp_current_usd" in wide.columns:
        wide["debt_to_gdp_ratio"] = (
            wide["public_debt_pct_gdp"] / 100
        ).round(4)

    # Drop the intermediate columns used only for derived features
    wide.drop(
        columns=["population_total", "public_debt_pct_gdp"],
        errors="ignore",
        inplace=True
    )

    # ── Completeness metrics ──────────────────────────────────
    feature_cols = [c for c in wide.columns
                    if c not in ["country_code", "country_name", "year"]]
    wide["non_null_feature_count"] = wide[feature_cols].notna().sum(axis=1)
    wide["completeness_pct"] = (
        wide["non_null_feature_count"] / len(feature_cols) * 100
    ).round(2)

    # ── Add pipeline observability columns ────────────────────
    wide["pipeline_run_id"] = run_id
    wide["loaded_at"] = datetime.now(timezone.utc)

    # ── Build insert rows ─────────────────────────────────────
    def safe(val):
        """Convert numpy types and NaN to Python native for psycopg2."""
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        if isinstance(val, (np.integer,)):
            return int(val)
        if isinstance(val, (np.floating,)):
            return float(val)
        return val

    cols = [
        "country_code", "country_name", "year",
        "gdp_growth_pct", "gdp_current_usd", "gni_per_capita_usd",
        "inflation_pct", "current_account_pct_gdp", "fdi_net_inflows_pct_gdp",
        "unemployment_pct", "gini_index", "life_expectancy_years",
        "school_enrollment_primary", "poverty_headcount_ratio",
        "broad_money_pct_gdp", "bank_capital_to_assets_pct",
        "domestic_credit_pct_gdp", "co2_emissions_kt", "renewable_energy_pct",
        "gdp_per_capita_usd", "debt_to_gdp_ratio",
        "non_null_feature_count", "completeness_pct",
        "pipeline_run_id", "loaded_at",
    ]

    rows = []
    for row in wide.itertuples(index=False):
        rows.append(tuple(
            safe(getattr(row, col, None)) for col in cols
        ))

    upsert_sql = f"""
        INSERT INTO feature_matrix ({", ".join(cols)})
        VALUES %s
        ON CONFLICT (country_code, year)
        DO UPDATE SET
            {", ".join(
                f"{c} = EXCLUDED.{c}"
                for c in cols
                if c not in ("country_code", "year")
            )}
    """

    try:
        with conn.cursor() as cur:
            execute_values(cur, upsert_sql, rows, page_size=1000)
        conn.commit()
        log.info(f"Upserted {len(rows):,} rows into feature_matrix")
    except Exception as e:
        conn.rollback()
        log.error(f"Transform failed: {e}")
        raise
    finally:
        conn.close()

    duration = round(time.time() - start, 2)
    log.info(f"Transform complete | rows={len(rows):,} | duration={duration}s")

    context["ti"].xcom_push(key="rows_transformed", value=len(rows))
    context["ti"].xcom_push(key="transform_duration_sec", value=duration)

    return len(rows)

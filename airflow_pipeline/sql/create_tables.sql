-- ============================================================
-- World Bank Pipeline — Table DDL
-- Schema: medallion pattern (bronze → silver → gold)
-- Database: worldbank_pipeline
-- ============================================================


-- ── Bronze layer: raw_indicators ─────────────────────────────
-- Exact copy of CSV rows. No transformation applied.
-- Append-only — never updated, never deleted.
-- This is your audit trail and replay source.

CREATE TABLE IF NOT EXISTS raw_indicators (
    id              BIGSERIAL PRIMARY KEY,
    country_code    VARCHAR(10)     NOT NULL,
    country_name    VARCHAR(100)    NOT NULL,
    series_code     VARCHAR(50)     NOT NULL,
    series_name     VARCHAR(255)    NOT NULL,
    year            SMALLINT        NOT NULL,
    value           TEXT,           -- kept as TEXT intentionally: raw = no casting
    source          VARCHAR(10)     NOT NULL,  -- QPSD / WDI / SPI
    ingested_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- Composite index on the natural key — speeds up silver layer reads
CREATE INDEX IF NOT EXISTS idx_raw_country_series_year
    ON raw_indicators (country_code, series_code, year);

-- Partial index on source — speeds up filtering by dataset origin
CREATE INDEX IF NOT EXISTS idx_raw_source
    ON raw_indicators (source);


-- ── Silver layer: cleaned_indicators ─────────────────────────
-- Nulls handled, types cast, duplicates removed.
-- '..' World Bank missing value marker replaced with NULL.
-- Upsert pattern: unique on (country_code, series_code, year, source)

CREATE TABLE IF NOT EXISTS cleaned_indicators (
    id              BIGSERIAL PRIMARY KEY,
    country_code    VARCHAR(10)     NOT NULL,
    country_name    VARCHAR(100)    NOT NULL,
    series_code     VARCHAR(50)     NOT NULL,
    series_name     VARCHAR(255)    NOT NULL,
    year            SMALLINT        NOT NULL,
    value           NUMERIC(20, 6), -- cast from TEXT, NULL if missing
    source          VARCHAR(10)     NOT NULL,
    cleaned_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),

    -- Natural key constraint — enforces deduplication at DB level
    CONSTRAINT uq_cleaned_natural_key
        UNIQUE (country_code, series_code, year, source)
);

CREATE INDEX IF NOT EXISTS idx_cleaned_country_year
    ON cleaned_indicators (country_code, year);

CREATE INDEX IF NOT EXISTS idx_cleaned_series
    ON cleaned_indicators (series_code);


-- ── Gold layer: feature_matrix ────────────────────────────────
-- Wide format: one row per country per year.
-- Each indicator pivoted into its own column.
-- Derived ratio features appended.
-- pipeline_run_id links every row back to the Airflow DAG run
-- that produced it — full observability and traceability.

CREATE TABLE IF NOT EXISTS feature_matrix (
    id                          BIGSERIAL PRIMARY KEY,

    -- Natural key
    country_code                VARCHAR(10)     NOT NULL,
    country_name                VARCHAR(100)    NOT NULL,
    year                        SMALLINT        NOT NULL,
    region                      VARCHAR(100),

    -- Economic indicators
    gdp_growth_pct              NUMERIC(12, 4),
    gdp_current_usd             NUMERIC(20, 2),
    gni_per_capita_usd          NUMERIC(12, 2),
    inflation_pct               NUMERIC(12, 4),
    current_account_pct_gdp     NUMERIC(12, 4),
    fdi_net_inflows_pct_gdp     NUMERIC(12, 4),
    unemployment_pct            NUMERIC(12, 4),

    -- Social indicators
    gini_index                  NUMERIC(8, 2),
    life_expectancy_years       NUMERIC(8, 2),
    school_enrollment_primary   NUMERIC(8, 2),
    poverty_headcount_ratio     NUMERIC(8, 2),

    -- Financial indicators
    broad_money_pct_gdp         NUMERIC(12, 4),
    bank_capital_to_assets_pct  NUMERIC(8, 2),
    domestic_credit_pct_gdp     NUMERIC(12, 4),

    -- Environmental indicators
    co2_emissions_kt            NUMERIC(16, 2),
    renewable_energy_pct        NUMERIC(8, 2),

    -- Derived ratio features (built in transform task)
    gdp_per_capita_usd          NUMERIC(16, 2),  -- gdp / population
    debt_to_gdp_ratio           NUMERIC(12, 4),  -- public debt / gdp

    -- Data quality columns
    non_null_feature_count      SMALLINT,        -- how many indicators populated
    completeness_pct            NUMERIC(5, 2),   -- % of columns that are non-null

    -- Pipeline observability columns
    pipeline_run_id             VARCHAR(50)  NOT NULL,  -- Airflow DAG run ID
    loaded_at                   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    -- Natural key constraint — upsert safe
    CONSTRAINT uq_feature_matrix_natural_key
        UNIQUE (country_code, year)
);

CREATE INDEX IF NOT EXISTS idx_feature_country_year
    ON feature_matrix (country_code, year);

CREATE INDEX IF NOT EXISTS idx_feature_region
    ON feature_matrix (region);

CREATE INDEX IF NOT EXISTS idx_feature_pipeline_run
    ON feature_matrix (pipeline_run_id);


-- ── Pipeline run log ──────────────────────────────────────────
-- Tracks every DAG execution: row counts per layer,
-- quality check results, and SLA timing.
-- This is what you show an interviewer when they ask
-- "how do you monitor your pipelines?"

CREATE TABLE IF NOT EXISTS pipeline_run_log (
    id                  BIGSERIAL PRIMARY KEY,
    pipeline_run_id     VARCHAR(50)     NOT NULL,
    dag_id              VARCHAR(100)    NOT NULL,
    run_started_at      TIMESTAMPTZ     NOT NULL,
    run_completed_at    TIMESTAMPTZ,

    -- Row counts per layer
    rows_ingested       INTEGER,
    rows_cleaned        INTEGER,
    rows_loaded         INTEGER,

    -- Data quality results
    quality_passed      BOOLEAN,
    null_pct_threshold  NUMERIC(5, 2),
    null_pct_actual     NUMERIC(5, 2),
    quality_notes       TEXT,

    -- SLA tracking
    ingest_duration_sec     NUMERIC(8, 2),
    clean_duration_sec      NUMERIC(8, 2),
    transform_duration_sec  NUMERIC(8, 2),
    load_duration_sec       NUMERIC(8, 2),
    total_duration_sec      NUMERIC(8, 2),

    CONSTRAINT uq_pipeline_run UNIQUE (pipeline_run_id)
);

def _clean_chunk(df: pd.DataFrame) -> pd.DataFrame:
    # Strip whitespace from string columns
    for col in ["country_code", "country_name", "series_code",
                "series_name", "source"]:
        df[col] = df[col].astype(str).str.strip()

    # Replace World Bank missing marker
    df["value"] = df["value"].replace({"..": None, "nan": None, "": None})

    # Cast value to numeric
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Drop rows missing natural key components
    before = len(df)
    df = df.dropna(subset=["country_code", "series_code", "year"])
    dropped_nulls = before - len(df)
    if dropped_nulls > 0:
        log.warning(f"Dropped {dropped_nulls:,} rows with null natural key")

    # Deduplicate on natural key
    before = len(df)
    df = df.drop_duplicates(
        subset=["country_code", "series_code", "year", "source"],
        keep="last",
    )
    dropped_dupes = before - len(df)
    if dropped_dupes > 0:
        log.info(f"Removed {dropped_dupes:,} duplicate rows")

    # Cast year to int
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

    CHUNK_SIZE = 100_000

    try:
        with conn, conn.cursor() as cur:
            for chunk in pd.read_sql(query, conn, chunksize=CHUNK_SIZE):
                log.info(f"Read chunk with {len(chunk):,} rows from raw_indicators")

                df = _clean_chunk(chunk)

                if df.empty:
                    log.info("Chunk became empty after cleaning; skipping upsert")
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

                execute_values(cur, upsert_sql, rows, page_size=10_000)
                total_rows += len(rows)
                log.info(
                    f"Upserted {len(rows):,} rows into cleaned_indicators "
                    f"(cumulative {total_rows:,})"
                )

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


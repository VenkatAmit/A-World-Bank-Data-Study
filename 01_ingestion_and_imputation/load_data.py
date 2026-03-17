"""
load_data.py
------------
Imports categorized World Bank CSV files into a normalized MySQL database.
Searches for CSV files in the current directory and subdirectories,
matches them to the expected table schema, and batch-imports data.

Database: worldbankfocused (MySQL)
Tables: countries, series, publicdebtindicators, statisticalindicators,
        environmentalindicators, economicalindicators, financialindicators,
        socialindicators

Usage:
    python load_data.py
    (Run after data_split.py has generated the split CSV files)
"""

import mysql.connector
import pandas as pd
import os
import time
import glob

# ─── Database connection parameters ───────────────────────────────────────────
DB_USER = "root"
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_HOST = "localhost"
DB_NAME = "worldbankfocused"

# ─── Expected column schemas per table ────────────────────────────────────────
EXPECTED_COLUMNS = {
    "countries":              ["countrycode", "countryname"],
    "series":                 ["seriescode", "seriesname", "category"],
    "publicdebtindicators":   ["countrycode", "countryname", "seriescode", "seriesname", "Year", "quarter", "Value"],
    "statisticalindicators":  ["countrycode", "countryname", "seriescode", "seriesname", "Year", "Value"],
    "environmentalindicators":["countrycode", "countryname", "seriescode", "seriesname", "Year", "Value"],
    "economicalindicators":   ["countrycode", "countryname", "seriescode", "seriesname", "Year", "Value"],
    "financialindicators":    ["countrycode", "countryname", "seriescode", "seriesname", "Year", "Value"],
    "socialindicators":       ["countrycode", "countryname", "seriescode", "seriesname", "Year", "Value"],
}

REQUIRED_TABLES = list(EXPECTED_COLUMNS.keys())


def find_csv_files():
    """Recursively find all CSV files in current directory and subdirectories."""
    print("Searching for CSV files in current directory and subdirectories...")
    current_dir = os.getcwd()
    print(f"Current directory: {current_dir}")

    csv_files = [
        os.path.join(root, file)
        for root, dirs, files in os.walk(current_dir)
        for file in files
        if file.endswith(".csv")
    ]

    if csv_files:
        print(f"\nFound {len(csv_files)} CSV files:")
        for f in csv_files:
            print(f"  - {f}")
    else:
        print("No CSV files found.")

    return csv_files


def match_csv_files():
    """Match discovered CSV files to expected database table names."""
    csv_files = find_csv_files()
    if not csv_files:
        return None

    table_files = {}
    for table in REQUIRED_TABLES:
        for file in csv_files:
            basename = os.path.basename(file).lower()
            # Exact match: filename == tablename.csv
            if basename == f"{table}.csv":
                table_files[table] = file
                break
            # Partial match: tablename is contained in filename
            elif table.lower() in basename:
                table_files[table] = file
                break
        if table not in table_files:
            print(f"Could not find a CSV file for table: {table}")

    return table_files


def import_csv_to_table(filepath, tablename, conn, cursor, batch_size=1000):
    """
    Import a CSV file into a MySQL table using batch inserts.

    Args:
        filepath   : Path to the CSV file
        tablename  : Target MySQL table name
        conn       : MySQL connection object
        cursor     : MySQL cursor object
        batch_size : Number of rows per INSERT batch (default 1000)

    Returns:
        Number of rows successfully imported
    """
    start_time = time.time()
    print(f"\nImporting data from {filepath} into {tablename}...")

    try:
        df = pd.read_csv(filepath)
        if df.empty:
            print(f"Warning: File {filepath} is empty. Skipping...")
            return 0

        total_rows = len(df)
        print(f"Found {total_rows} rows to import.")
        print(f"First 3 rows:\n{df.head(3)}")
        print(f"Columns: {', '.join(df.columns)}")

        # Validate columns against expected schema
        if tablename in EXPECTED_COLUMNS:
            expected = EXPECTED_COLUMNS[tablename]
            if not all(col in df.columns for col in expected):
                print(f"Warning: Column mismatch for table '{tablename}'")
                print(f"  Expected : {expected}")
                print(f"  Found    : {df.columns.tolist()}")
                confirm = input("Proceed with import anyway? (y/n): ")
                if confirm.lower() != "y":
                    return 0

        # Build INSERT query
        columns = df.columns.tolist()
        placeholders = ", ".join(["%s"] * len(columns))
        query = f"INSERT INTO {tablename} ({', '.join(columns)}) VALUES ({placeholders})"

        rows_imported = 0
        for i in range(0, total_rows, batch_size):
            batch = df.iloc[i : i + batch_size]
            values = [tuple(x) for x in batch.to_numpy()]
            try:
                cursor.executemany(query, values)
                conn.commit()
                rows_imported += len(values)
                pct = rows_imported / total_rows * 100
                elapsed = time.time() - start_time
                print(f"  Progress: {rows_imported}/{total_rows} rows ({pct:.1f}%) — {elapsed:.1f}s elapsed")
            except Exception as e:
                print(f"  Error importing batch: {e}")
                print("  Continuing with next batch...")

        total_time = time.time() - start_time
        print(f"Completed: {rows_imported} rows imported into '{tablename}' in {total_time:.2f}s")
        return rows_imported

    except Exception as e:
        print(f"Error importing data to {tablename}: {e}")
        return 0


def main():
    """Find CSVs, connect to MySQL, and import all tables."""
    table_files = match_csv_files()
    if not table_files:
        print("Could not find the required CSV files. Make sure they are in the directory or subdirectories.")
        return

    # Check for missing tables
    missing_tables = [t for t in REQUIRED_TABLES if t not in table_files]
    if missing_tables:
        print(f"\nWarning: Could not find CSV files for: {', '.join(missing_tables)}")
        confirm = input("Proceed with the tables we found? (y/n): ")
        if confirm.lower() != "y":
            return

    print(f"\nConnecting to MySQL database '{DB_NAME}'...")
    try:
        conn = mysql.connector.connect(
            host=DB_HOST,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
        )
        cursor = conn.cursor()

        import_results = {}

        # Import reference tables first
        for ref_table in ["countries", "series"]:
            if ref_table in table_files:
                import_results[ref_table] = import_csv_to_table(
                    table_files[ref_table], ref_table, conn, cursor
                )

        # Import fact/indicator tables
        for table in [t for t in REQUIRED_TABLES if t not in ("countries", "series")]:
            if table in table_files:
                import_results[table] = import_csv_to_table(
                    table_files[table], table, conn, cursor
                )

        # Summary
        print("\n" + "=" * 50)
        print("Import Summary")
        print("=" * 50)
        total_records = 0
        for table, count in import_results.items():
            print(f"  {table}: {count:,} records imported")
            total_records += count
        print(f"\nTotal records imported: {total_records:,}")

    except mysql.connector.Error as err:
        print(f"Failed to connect to MySQL database: {err}")
    finally:
        try:
            cursor.close()
            conn.close()
            print("Database connection closed.")
        except Exception:
            pass


if __name__ == "__main__":
    main()

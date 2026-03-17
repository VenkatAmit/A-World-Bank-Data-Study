"""
data_split.py
-------------
Splits the raw World Bank CSV dataset into normalized, category-specific
CSV files ready for ingestion into MySQL via load_data.py.

Input  : One raw World Bank CSV (wide format — countries x series x years)
Outputs: countries.csv, series.csv, and one CSV per indicator category:
         - publicdebtindicators.csv
         - statisticalindicators.csv
         - environmentalindicators.csv
         - economicalindicators.csv
         - financialindicators.csv
         - socialindicators.csv

Usage:
    python data_split.py --input <path_to_raw_csv> [--output_dir <dir>]
"""

import pandas as pd
import os
import argparse
import re

# ─── Category keyword mapping ──────────────────────────────────────────────────
# Maps indicator table names to keywords found in SeriesName / SeriesCode.
CATEGORY_KEYWORDS = {
    "publicdebtindicators": [
        "debt", "deficit", "fiscal", "government bond", "sovereign",
        "borrowing", "public finance", "interest payment",
    ],
    "environmentalindicators": [
        "co2", "emission", "forest", "renewable", "energy", "climate",
        "carbon", "pollution", "water", "sanitation", "land",
    ],
    "economicalindicators": [
        "gdp", "gni", "inflation", "trade", "export", "import",
        "current account", "unemployment", "labor", "employment",
        "gross", "growth", "price", "wage",
    ],
    "financialindicators": [
        "credit", "bank", "lending", "interest rate", "financial",
        "capital", "foreign direct", "fdi", "stock market", "insurance",
        "remittance", "portfolio",
    ],
    "socialindicators": [
        "poverty", "education", "health", "mortality", "fertility",
        "population", "literacy", "gini", "inequality", "life expectancy",
        "undernourishment", "hiv", "immunization",
    ],
    "statisticalindicators": [],  # catch-all — assigned last
}


def parse_args():
    parser = argparse.ArgumentParser(description="Split raw World Bank CSV into normalized tables.")
    parser.add_argument(
        "--input", required=True,
        help="Path to the raw World Bank CSV file."
    )
    parser.add_argument(
        "--output_dir", default="split_output",
        help="Directory to write the split CSV files (default: split_output/)."
    )
    return parser.parse_args()


def load_raw_data(filepath: str) -> pd.DataFrame:
    """Load the raw World Bank CSV, handling the typical multi-header layout."""
    print(f"Loading raw data from: {filepath}")
    df = pd.read_csv(filepath, skiprows=4)  # World Bank CSVs have 4 metadata rows
    df.columns = [str(c).strip() for c in df.columns]
    print(f"  Loaded {len(df):,} rows x {len(df.columns)} columns")
    return df


def extract_year_columns(df: pd.DataFrame) -> list:
    """Return all column names that represent years (4-digit integers)."""
    return [c for c in df.columns if re.match(r'^\d{4}$', c)]


def build_countries_table(df: pd.DataFrame) -> pd.DataFrame:
    """Extract unique country reference table."""
    countries = (
        df[["Country Code", "Country Name"]]
        .drop_duplicates()
        .rename(columns={"Country Code": "countrycode", "Country Name": "countryname"})
        .sort_values("countrycode")
        .reset_index(drop=True)
    )
    print(f"  countries: {len(countries):,} rows")
    return countries


def build_series_table(df: pd.DataFrame, category_map: dict) -> pd.DataFrame:
    """Extract unique series reference table with assigned category."""
    series = (
        df[["Indicator Code", "Indicator Name"]]
        .drop_duplicates()
        .rename(columns={"Indicator Code": "seriescode", "Indicator Name": "seriesname"})
        .reset_index(drop=True)
    )
    series["category"] = series.apply(
        lambda row: assign_category(row["seriesname"], row["seriescode"], category_map),
        axis=1,
    )
    print(f"  series: {len(series):,} rows")
    return series


def assign_category(series_name: str, series_code: str, category_map: dict) -> str:
    """Assign an indicator to a category based on keyword matching."""
    combined = (series_name + " " + series_code).lower()
    for category, keywords in category_map.items():
        if category == "statisticalindicators":
            continue  # skip catch-all in first pass
        if any(kw in combined for kw in keywords):
            return category
    return "statisticalindicators"  # default catch-all


def melt_to_long_format(df: pd.DataFrame, year_cols: list) -> pd.DataFrame:
    """
    Convert the wide-format World Bank data (one column per year)
    into a long format: one row per (country, indicator, year).
    """
    id_vars = ["Country Code", "Country Name", "Indicator Code", "Indicator Name"]
    melted = df[id_vars + year_cols].melt(
        id_vars=id_vars,
        var_name="Year",
        value_name="Value",
    )
    melted["Year"] = melted["Year"].astype(int)
    melted = melted.dropna(subset=["Value"])  # drop missing observations
    melted = melted.rename(columns={
        "Country Code": "countrycode",
        "Country Name": "countryname",
        "Indicator Code": "seriescode",
        "Indicator Name": "seriesname",
    })
    print(f"  Long-format rows (non-null): {len(melted):,}")
    return melted


def split_by_category(
    long_df: pd.DataFrame,
    series_df: pd.DataFrame,
    category_map: dict,
) -> dict:
    """
    Split the long-format DataFrame into per-category DataFrames.
    Returns a dict: {table_name -> DataFrame}
    """
    # Build a lookup: seriescode -> category
    code_to_category = dict(zip(series_df["seriescode"], series_df["category"]))
    long_df = long_df.copy()
    long_df["category"] = long_df["seriescode"].map(code_to_category).fillna("statisticalindicators")

    result = {}
    for category in category_map:
        subset = long_df[long_df["category"] == category].drop(columns=["category"])

        if category == "publicdebtindicators":
            # Public debt data may carry a quarter column — add placeholder
            subset = subset.copy()
            subset.insert(subset.columns.get_loc("Year") + 1, "quarter", None)

        result[category] = subset.reset_index(drop=True)
        print(f"  {category}: {len(subset):,} rows")

    return result


def save_outputs(countries: pd.DataFrame, series: pd.DataFrame,
                 category_dfs: dict, output_dir: str) -> None:
    """Write all output CSVs to the specified directory."""
    os.makedirs(output_dir, exist_ok=True)

    countries.to_csv(os.path.join(output_dir, "countries.csv"), index=False)
    print(f"  Saved: {output_dir}/countries.csv")

    series.to_csv(os.path.join(output_dir, "series.csv"), index=False)
    print(f"  Saved: {output_dir}/series.csv")

    for table_name, df in category_dfs.items():
        out_path = os.path.join(output_dir, f"{table_name}.csv")
        df.to_csv(out_path, index=False)
        print(f"  Saved: {out_path}  ({len(df):,} rows)")


def main():
    args = parse_args()

    if not os.path.isfile(args.input):
        print(f"ERROR: Input file not found: {args.input}")
        return

    print("\n" + "=" * 60)
    print("  World Bank Data Splitter")
    print("=" * 60)

    # 1. Load raw CSV
    raw_df = load_raw_data(args.input)

    # 2. Identify year columns
    year_cols = extract_year_columns(raw_df)
    print(f"  Year range detected: {min(year_cols)} — {max(year_cols)} ({len(year_cols)} years)")

    # 3. Build reference tables
    print("\nBuilding reference tables...")
    countries_df = build_countries_table(raw_df)
    series_df = build_series_table(raw_df, CATEGORY_KEYWORDS)

    # 4. Melt to long format
    print("\nMelting to long format...")
    long_df = melt_to_long_format(raw_df, year_cols)

    # 5. Split by indicator category
    print("\nSplitting by indicator category...")
    category_dfs = split_by_category(long_df, series_df, CATEGORY_KEYWORDS)

    # 6. Save all outputs
    print(f"\nSaving outputs to: {args.output_dir}/")
    save_outputs(countries_df, series_df, category_dfs, args.output_dir)

    # 7. Summary
    total_rows = sum(len(df) for df in category_dfs.values())
    print("\n" + "=" * 60)
    print("  Split Complete — Summary")
    print("=" * 60)
    print(f"  Countries     : {len(countries_df):,}")
    print(f"  Series        : {len(series_df):,}")
    print(f"  Total records : {total_rows:,}")
    for name, df in category_dfs.items():
        print(f"  {name:<30}: {len(df):,} rows")
    print(f"\nNext step: run  python load_data.py  from the {args.output_dir}/ directory")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()

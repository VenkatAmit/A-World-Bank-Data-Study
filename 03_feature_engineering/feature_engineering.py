"""
feature_engineering.py
-----------------------
Merges cleaned indicator CSVs into a single wide-format feature matrix
for downstream modelling (economic resilience, social equity, financial dev).

Inputs  : Cleaned CSVs in 03_feature_engineering/
Outputs : Combined_Indicators_Data.csv  (one row per country-year)

Steps
-----
1. Load each domain-specific CSV (Economic, Social, Financial, etc.)
2. Pivot from long → wide so each series_code becomes a column
3. Merge all domains on (country_code, country_name, year)
4. Drop columns with > 70 % missingness (mirrors imputation threshold)
5. Forward-fill then backward-fill remaining NaN within each country group
6. Add derived ratio features used in modelling
7. Save to Combined_Indicators_Data.csv
"""

import pandas as pd
import numpy as np
import os

# ── Configuration ────────────────────────────────────────────────────────────
DATA_DIR  = os.path.dirname(__file__)          # same folder as this script
OUTPUT    = os.path.join(DATA_DIR, "Combined_Indicators_Data.csv")
MISS_THRESH = 0.70                             # drop col if > 70 % missing

DOMAIN_FILES = {
    "economic":    "Economical_Indicators.csv",
    "environmental": "Environmental_Indicators.csv",
    "financial":   "Financial_Indicators.csv",
    "public_debt": "Public_Debt_Indicators.csv",
    "social":      "Social_Indicators.csv",
    "statistical": "Statistical_Indicators.csv",
}

ID_COLS  = ["country_name", "country_code", "year"]
KEY_COLS = ID_COLS + ["series_code", "value"]


# ── Helper: load + pivot one domain file ─────────────────────────────────────
def load_and_pivot(filepath: str, domain: str) -> pd.DataFrame:
    """Read a long-format indicator CSV and pivot to wide format."""
    df = pd.read_csv(filepath)

    # Standardise column names
    df.columns = df.columns.str.strip().str.lower().str.replace(" ", "_")

    required = {"country_name", "country_code", "series_code", "year", "value"}
    missing  = required - set(df.columns)
    if missing:
        raise ValueError(f"[{domain}] Missing columns: {missing}")

    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    # Pivot: each series_code → its own column
    wide = df.pivot_table(
        index=["country_name", "country_code", "year"],
        columns="series_code",
        values="value",
        aggfunc="mean",   # average if duplicate rows exist
    ).reset_index()

    # Prefix columns with domain to avoid collisions
    rename = {
        col: f"{domain}__{col}"
        for col in wide.columns
        if col not in ["country_name", "country_code", "year"]
    }
    wide.rename(columns=rename, inplace=True)
    return wide


# ── Main pipeline ─────────────────────────────────────────────────────────────
def build_feature_matrix() -> pd.DataFrame:
    frames = []
    for domain, filename in DOMAIN_FILES.items():
        path = os.path.join(DATA_DIR, filename)
        if not os.path.exists(path):
            print(f"  [WARN] {filename} not found — skipping {domain}")
            continue
        df = load_and_pivot(path, domain)
        print(f"  Loaded {domain}: {df.shape}")
        frames.append(df)

    if not frames:
        raise RuntimeError("No domain files loaded — check DATA_DIR path.")

    # Merge all domains on country + year
    combined = frames[0]
    for df in frames[1:]:
        combined = combined.merge(df, on=["country_name", "country_code", "year"], how="outer")

    print(f"\nRaw merged shape: {combined.shape}")

    # ── Drop high-missingness columns ────────────────────────────────────────
    miss_rate = combined.isnull().mean()
    drop_cols = miss_rate[miss_rate > MISS_THRESH].index.tolist()
    combined.drop(columns=drop_cols, inplace=True)
    print(f"Dropped {len(drop_cols)} columns with >{int(MISS_THRESH*100)}% missingness")

    # ── Fill remaining NaN within each country (time-series imputation) ──────
    combined.sort_values(["country_code", "year"], inplace=True)
    num_cols = combined.select_dtypes(include="number").columns
    combined[num_cols] = (
        combined.groupby("country_code")[num_cols]
        .transform(lambda s: s.ffill().bfill())
    )

    # ── Derived ratio features ────────────────────────────────────────────────
    # GDP per capita proxy: use economic__NY.GDP.MKTP.CD / economic__SP.POP.TOTL if present
    gdp_col  = "economic__NY.GDP.MKTP.CD"
    pop_col  = "economic__SP.POP.TOTL"
    if gdp_col in combined.columns and pop_col in combined.columns:
        combined["feat__gdp_per_capita"] = combined[gdp_col] / combined[pop_col].replace(0, np.nan)

    # Debt-to-GDP ratio
    debt_col = "public_debt__DT.DOD.DECT.CD"
    if debt_col in combined.columns and gdp_col in combined.columns:
        combined["feat__debt_to_gdp"] = combined[debt_col] / combined[gdp_col].replace(0, np.nan)

    print(f"Final feature matrix shape: {combined.shape}")
    return combined


if __name__ == "__main__":
    print("Building feature matrix …")
    feat_df = build_feature_matrix()
    feat_df.to_csv(OUTPUT, index=False)
    print(f"Saved → {OUTPUT}")

    # Quick sanity check
    print("\nColumn sample:")
    print(feat_df.columns[:10].tolist())
    print(feat_df.head(3).to_string())

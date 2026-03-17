# A-World-Bank-Data-Study

> **Analysis of Economic Resilience, Social Equity, and Financial Systems Development**  
> World Bank Open Data · 217 countries · 2021–2023

---

## Authors

| Name | Role |
|------|------|
| Venkat Amit Kommineni | Data Engineering, Modeling |
| Rahul Preetham Roshan Parasa | Feature Engineering, EDA |
| Bala Rama Murthy Raju Vemanamanda | Transformation, Financial Modeling |
| Venkata Sai Akshith Kumar Bathula | Social Equity Modeling |

---

## Project Overview

This repository contains the full end-to-end pipeline for a multi-domain World Bank data study. Using indicator data from 2021–2023, we build and evaluate machine learning models for three country-level targets:

| Target | Type | Best Model |
|--------|------|------------|
| **Economic Resilience** | Binary classification (Resilient / Not Resilient) | Random Forest |
| **Social Equity Index** | Regression | Ridge Regression + ANN |
| **Financial Development Index (FDI)** | Regression | XGBoost + SHAP |

---

## Repository Structure

```
A-World-Bank-Data-Study/
├── data/raw/                          # Raw World Bank CSVs (7 indicator files)
│
├── 01_ingestion_and_imputation/       # Data loading, cleaning, KNN imputation
│   ├── load_data.py                   # Batch MySQL loader (batch size 1000)
│   ├── data_split.py                  # Train/val/test split by country-year
│   ├── Data_preprocessing_pipeline.ipynb
│   └── Imputed_and_cleaned_data.csv
│
├── 02_initial_eda/                    # Exploratory data analysis
│   ├── eda_analysis.ipynb             # Missing values, distributions, correlations
│   ├── regional_coverage.png
│   ├── regional_indicator_coverage.png
│   └── economic_values_distribution.png
│
├── 03_feature_engineering/            # Feature matrix construction
│   ├── feature_engineering.py         # Long→wide pivot, merge, derived ratios
│   ├── Combined_Indicators_Data.csv
│   └── [domain CSVs per indicator category]
│
├── 04_transformation/                 # Standardisation, encoding, pivot to model-ready format
│   ├── Transformation_EDA_Models.ipynb
│   └── pivoted_transformed_data.csv
│
├── 05_modeling_economic_resilience/   # Binary classification
│   ├── Economic_Resilience.ipynb
│   └── [PNGs: GDP trajectories, volatility, region boxplots]
│
├── 06_modeling_social_equity/         # Ridge Regression + ANN
│   ├── Social_Equity.ipynb
│   └── [PNGs: ridge path, feature importance, ANN training history]
│
├── 07_modeling_financial_development/ # XGBoost + SHAP
│   ├── FDI.ipynb
│   ├── FDI_SHAP_values.csv
│   └── [PNGs: financial indicator trends]
│
├── requirements.txt
└── README.md
```

---

## Pipeline

```
Raw CSVs (data/raw/)
    │
    ▼
01  Ingest → standardise column names → melt wide→long
    → KNN + Iterative imputation → data_split.py
    │
    ▼
02  EDA → missing value heatmaps → distributions → correlation heatmaps
    │
    ▼
03  Feature Engineering → pivot long→wide per domain
    → outer-join all 6 domains on (country_code, year)
    → drop >70% missing columns → ffill/bfill per country
    → derive GDP per capita, Debt-to-GDP ratio features
    │
    ▼
04  Transformation → StandardScaler → LabelEncoder
    → pivot to final model-ready matrix
    │
    ▼
05  Economic Resilience Model (Random Forest binary classifier)
06  Social Equity Model (Ridge Regression + ANN)
07  Financial Development Model (XGBoost + SHAP analysis)
```

---

## Key Results

### Economic Resilience (Binary Classification)
- Random Forest outperformed Logistic Regression and SVM
- Key features: GDP growth rate, current account balance, inflation volatility
- Regional analysis shows Sub-Saharan Africa and South Asia with highest non-resilience rates

### Social Equity Index (Regression)
- Ridge Regression (alpha tuned via cross-validation) achieved lowest RMSE
- ANN (3-layer MLP) converged after ~50 epochs; residuals approximately normal
- Primary drivers: school enrollment (primary), access to clean water, GINI coefficient

### Financial Development Index (XGBoost + SHAP)
- SHAP values identify broad money growth and bank capital-to-assets ratio as top predictors
- FDI scores range 0–1; high-income OECD countries cluster near 0.8+

---

## Data Sources

| File | Description |
|------|-------------|
| Economic_Indicators.csv | GDP, inflation, trade, current account (annual) |
| Environmental_Indicators.csv | CO2 emissions, forest area, energy use |
| Public_Debt_Indicators.csv | Debt stocks and flows (quarterly) |
| Social_Indicators.csv | Education, health, poverty, GINI |
| Statistical_Indicators.csv | Data quality and coverage metadata |
| Countries.csv | ISO country codes and region mapping |
| Series.csv | Indicator metadata and definitions |

Source: [World Bank Open Data](https://data.worldbank.org/) — data range 2021–2023.

---

## Setup

```bash
git clone https://github.com/VenkatAmit/A-World-Bank-Data-Study.git
cd A-World-Bank-Data-Study
pip install -r requirements.txt

# Run the full pipeline
python 01_ingestion_and_imputation/load_data.py
python 01_ingestion_and_imputation/data_split.py
python 03_feature_engineering/feature_engineering.py
# Then open notebooks in 04–07 sequentially
```

---

## Tech Stack

`Python 3.10` · `pandas` · `numpy` · `scikit-learn` · `xgboost` · `shap`  
`matplotlib` · `seaborn` · `plotly` · `MySQL` · `Google Colab`

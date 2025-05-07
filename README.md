# A-World-Bank-Data-Study
Analysis of Economic Resilience, Social Equity, and Financial Systems Development

Project Overview:

This repository contains the code, data, and documentation for a comprehensive analysis of economic resilience, social equity, and financial systems development across countries using World Bank data from 2021 to 2023. The project employs advanced machine learning techniques to model and predict these three critical development indicators.

Authors: 

Venkat Amit Kommineni,
Rahul Preetham Roshan Parasa,
Bala Rama Murthy Raju Vemanamanda,
Venkata Sai Akshith Kumar Bathula

Research Objectives:

Economic Resilience: Build and evaluate a binary classification model to identify countries as "Resilient" or "Not Resilient" based on economic indicators.
Social Equity: Construct a normalized Social Equity Index and evaluate Ridge Regression and Artificial Neural Networks in predicting it.
Financial Development: Design a Financial Development Index (FDI) and assess the predictive performance of Random Forest and XGBoost regression models.

Data Sources:
The analysis draws on several World Bank datasets:

World Development Indicators (WDI)
Quarterly Public Sector Debt Indicators
Statistical Performance Indicators

Repository Structure:

├── Categorized series/          # Organized indicators by category
├── Economic Resilience/         # Analysis files for Economic Resilience modeling
├── FDI/                         # Files related to Financial Development Index
├── Imputation folder/           # Scripts and data for handling missing values
├── Initial Distributions/       # Analysis of data distributions before transformation
├── Social Equity/               # Social Equity Index analysis and models
├── Transformed data/            # Datasets after normalization and transformation
├── Worlddevelopmentindicators.csv  # Main World Bank development indicators
├── Quarterlypublicdebt.csv      # Quarterly public debt statistics
└── Statisticalperformanceindicators.csv  # Statistical performance metrics

Methodology:

Data Preprocessing & Imputation:

Records with >70% missingness were excluded
KNN and linear interpolation were applied based on country-wise missing value percentages
Final imputation was supplemented with series and year-wise mean values

Transformation:

Box-Cox transformation for strictly positive indicators
Yeo-Johnson transformation for variables containing zeros or negative values

Feature Engineering:

Economic Resilience: Binary classification based on thresholded indicators
Social Equity Index: Composite index formulation using normalized social indicators
Financial Development Index: Constructed from financial depth, access, efficiency, and stability metrics

Modeling Approach:

Economic Resilience: Logistic Regression with threshold optimization
Social Equity: Ridge Regression and Artificial Neural Networks
Financial Development: Random Forest and XGBoost

Key Findings:

Economic Resilience:

Model achieved 90% accuracy and 0.96 ROC-AUC
Top predictive features: Electrical outages impact, Industrial design applications, Total reserves, Rule of Law, GDP growth


Social Equity:

Ridge Regression: R² score of 0.98, RMSE of 1.68
ANN: R² score of 0.89, RMSE of 3.3
Key factors: Gender equality, financial inclusion for the poorest 40%, access to basic services


Financial Development:

XGBoost outperformed with R² score of 0.905, RMSE of 2.33
Critical features: Stock market activity, broad money growth, domestic credit access, bank stability


Regional Patterns:

East Asia & Pacific showed strongest performance across indicators
Sub-Saharan Africa and South Asia displayed systematic challenges
Central Asia demonstrated promising economic equality metrics despite other challenges



Policy Implications: 

For Enhancing Economic Resilience:

Invest in foreign reserve buffers and maintain current account stability
Strengthen rule of law and governance to build investor confidence
Develop flexible labor markets and reduce unemployment through targeted training programs

For Promoting Social Equity:

Focus on gender-sensitive financial inclusion, including mobile money for the bottom 40%
Prioritize rural infrastructure (electricity, clean cooking fuel, sanitation) to reduce rural-urban disparities
Improve maternal healthcare and access to basic education

For Developing Financial Systems:

Expand banking infrastructure (ATMs and branches) to enhance financial access in underserved regions
Promote capital market development through better regulation and financial literacy programs
Strengthen financial stability through enhanced monitoring of non-performing loans and capital adequacy

Required Libraries:

pandas,
numpy,
scikit-learn,
tensorflow,
xgboost,
matplotlib,
seaborn,
plotly,
scipy,
shap

Future Work:

Expand temporal analysis by incorporating data from additional years
Explore ensemble stacking and time-series deep learning models
Develop real-time dashboards for continuous monitoring
Include additional qualitative indicators on governance and political stability

Citation
If you use this code or methodology in your research, please cite:

Kommineni, V.A., Parasa, R.P.R., Vemanamanda, B.R.M., & Bathula, V.S.A.K. (2025). 
Analysis of Economic Resilience, Social Equity, and Financial Systems Development: 
A World Bank Data Study. California State University, Northridge.

Acknowledgments

California State University, Northridge
Dr. Akash Gupta
Professor Sheng, Qiuhua (Jessica)
Professor Eslami, Seyed Pouyan
World Bank for providing open access to development indicators

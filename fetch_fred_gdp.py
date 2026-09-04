import os
import urllib.request
import json
import pandas as pd
import numpy as np
import statsmodels.api as sm

# 1. Grab your hidden API key from the system environment
api_key = os.environ.get("FRED_API_KEY")

# Helper function to fetch a series from FRED and return a Pandas DataFrame
def fetch_fred_data(series_id, api_key):
    url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"
    response = urllib.request.urlopen(url)
    raw_data = json.loads(response.read().decode())
    
    dates, values = [], []
    for obs in raw_data['observations']:
        if obs["value"] != ".":
            dates.append(obs["date"])
            values.append(float(obs["value"]))
            
    return pd.DataFrame({series_id: values}, index=pd.to_datetime(dates))

# 2 & 3. Request GDP and Recession data from FRED
# Note: Using USRECQ (Quarterly) so it perfectly aligns with Quarterly GDP
df_gdp = fetch_fred_data("GDP", api_key)
df_rec = fetch_fred_data("USRECQ", api_key)

# 4. Merge the data into a single DataFrame
df = df_gdp.join(df_rec, how="left")
df.rename(columns={"GDP": "value", "USRECQ": "recession"}, inplace=True)
df["recession"] = df["recession"].fillna(0) # Fill any unmatched dates with 0 (no recession)

# Macroeconomic convention: Take the natural log of GDP before filtering
df["log_gdp"] = (np.log(df["value"]) * 100)

# 5. Apply Hodrick-Prescott (HP) Filter (lambda = 1600 for quarterly data)
hp_cycle, hp_trend = sm.tsa.filters.hpfilter(df["log_gdp"], lamb=1600)

# 6. Apply Hamilton Regression Filter (h=8, p=4 standard for quarterly data)
# Note: Hamilton filter yields NaNs for the first p + h - 1 entries
# h=8 is standard for quarterly data for 2 years * 4 quarterly, but cycles too big, so reduce to 4 for 1 year lookahead 
ham_result = sm.tsa.filters.hamilton_filter(df["log_gdp"], h=4, p=4) 
ham_cycle = ham_result.cycle
ham_trend = ham_result.trend

# 7. Combine raw data and filter outputs into a structured list, converting NaNs to None for JSON
filtered_output = []
for i in range(len(df)):
    date_str = df.index[i].strftime("%Y-%m-%d")
    filtered_output.append({
        "date": date_str,
        "gdp_value": df["value"].iloc[i],
        "log_gdp": df["log_gdp"].iloc[i],
        "hp_trend": float(hp_trend.iloc[i]) if not np.isnan(hp_trend.iloc[i]) else None,
        "hp_cycle": float(hp_cycle.iloc[i]) if not np.isnan(hp_cycle.iloc[i]) else None,
        "hamilton_trend": float(ham_trend.iloc[i]) if not np.isnan(ham_trend.iloc[i]) else None,
        "hamilton_cycle": float(ham_cycle.iloc[i]) if not np.isnan(ham_cycle.iloc[i]) else None,
        "recession": int(df["recession"].iloc[i]) # 1 for recession, 0 for expansion
    })

# 8. Create data folder if it doesn't exist, then save results to JSON
os.makedirs("data", exist_ok=True)
with open("data/gdp_filtered_data.json", "w") as f:
    json.dump(filtered_output, f, indent=4)

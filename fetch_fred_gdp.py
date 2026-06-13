import os
import urllib.request
import json

# 1. Grab your hidden API key from the system environment
api_key = os.environ.get("FRED_API_KEY")

# 2. Define the economic variable you want (e.g., GDP)
series_id = "GDP" 
url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series_id}&api_key={api_key}&file_type=json"

# 3. Request the data from FRED
response = urllib.request.urlopen(url)
raw_data = json.loads(response.read().decode())

# 4. Clean the data (equivalent to removing NaN values or slicing data in Matlab)
clean_data = []
for obs in raw_data['observations']:
    # Ensure data point isn't missing (FRED represents missing data as '.')
    if obs["value"] != ".":
        clean_data.append({
            "date": obs["date"],
            "value": float(obs["value"])
        })

# 5. Create data folder if it doesn't exist, then save the file inside it
os.makedirs("data", exist_ok=True)
with open("data/fred_data.json", "w") as f:
    json.dump(clean_data, f)

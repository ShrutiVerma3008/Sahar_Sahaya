# sahara_sahaya/utils/map_utils.py
import pandas as pd, folium
from geopy.distance import geodesic

def load_relief_centers(path="data/relief_centers.csv"):
    df = pd.read_csv(path)

    # normalise – keep missing cells from crashing the split
    df["supported_disasters"] = (
        df["supported_disasters"]
          .fillna("")                         # NaN -> empty string
          .astype(str)
          .str.replace(r"\s+", "", regex=True)  # trim spaces
          .str.split(r"[|,]")                 # allow "|" OR "," separators
    )
    return df

def filter_by_disaster(df: pd.DataFrame, disaster: str) -> pd.DataFrame:
    disaster = disaster.lower()

    def _matches(lst):
        if not isinstance(lst, list):
            return False
        return any(disaster == item.lower() for item in lst if item)

    return df[df["supported_disasters"].apply(_matches)]

def create_map(user_loc, relief_df):
    m = folium.Map(location=user_loc, zoom_start=14)
    folium.Marker(user_loc, tooltip="You are here",
                  icon=folium.Icon(color="blue", icon="user")).add_to(m)

    for _, r in relief_df.iterrows():
        dst = geodesic(user_loc, (r.latitude, r.longitude)).km
        mins = round(dst / 0.083)          # ≈ 5 km/h walking
        popup = (f"<b>{r.name}</b><br>Type: {r.type}<br>"
                 f"Inventory: {r.inventory}<br>Updated: {r.last_updated}<br>"
                 f"Distance: {dst:.2f} km<br>Time: {mins} min<br>"
                 f"Contact: {r.contact}")
        folium.Marker((r.latitude, r.longitude),
                      tooltip=f"{r.name} ({dst:.1f} km)",
                      popup=popup,
                      icon=folium.Icon(color="red", icon="plus")).add_to(m)
    return m


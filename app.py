# sahara_sahaya/app.py
# ----------------------------------------------------------
import os
import streamlit as st
import pandas as pd
from streamlit_folium import st_folium
from geopy.distance import geodesic

from utils.location_utils import geocode_location, detect_gps_location
from utils.map_utils     import load_relief_centers, create_map, filter_by_disaster
# ----------------------------------------------------------
import chardet
from io import BytesIO
import re

# ------------------------------------------------------------------
#  helper functions to load, clean, validate any relief-centre file
# ------------------------------------------------------------------

REQUIRED_COLS = [
    "name", "type", "latitude", "longitude",
    "inventory", "last_updated", "contact", "supported_disasters"
]

# Loose aliases we’re willing to map → canonical column names
ALIASES = {
    "name":  ["hospital_name", "facility name", "station name", "centre name", "center name", "name"],
    "type":  ["hospital_category", "category", "hospital_type", "centre type", "type"],
    "latitude":  ["lat", "latitude", "latitude(dd)", "lat_dd"],
    "longitude": ["lon", "long", "longitude", "longitude(dd)", "lng", "lng_dd"],
    "contact": ["mobile_number", "mobile", "telephone", "phone", "contact", "phone_no", "phone number"],
}

def detect_encoding(raw_bytes: bytes) -> str:
    """Return a safe text encoding for the given bytes."""
    enc = (chardet.detect(raw_bytes[:50_000])["encoding"] or "").lower()
    return "latin1" if enc in ("", "ascii", "unknown") else enc

def read_any_file(uploaded) -> pd.DataFrame:
    """Read CSV, XLS, or XLSX from a Streamlit uploader."""
    fn = uploaded.name.lower()
    raw = uploaded.read()
    uploaded.seek(0)                               # rewind after peek

    if fn.endswith((".xls", ".xlsx")):
        # Excel: let pandas choose a working engine
        return pd.read_excel(uploaded, dtype=str, engine="openpyxl" if fn.endswith("xlsx") else "xlrd")

    # CSV: detect encoding, skip bad lines
    enc = detect_encoding(raw)
    return pd.read_csv(
        BytesIO(raw),              # supply bytes again
        encoding=enc,
        engine="python",
        on_bad_lines="skip",
        dtype=str,
    )

def standardise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Return a DataFrame with the 8 required columns in order."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]

    out = pd.DataFrame(columns=REQUIRED_COLS)

    # ❶ map obvious 1-to-1 aliases
    for target, candidates in ALIASES.items():
        for cand in candidates:
            if cand in df.columns:
                out[target] = df[cand]
                break

    # ❷ split a single "lat,lon" cell if present
    if "location_coordinates" in df.columns and ("latitude" not in out or "longitude" not in out):
        coords = df["location_coordinates"].str.split(",", expand=True)
        out["latitude"]  = out.get("latitude",  coords[0])
        out["longitude"] = out.get("longitude", coords[1])

    # ❸ fill in still-missing required cols with blanks
    for col in REQUIRED_COLS:
        if col not in out:
            out[col] = ""

    # ❹ tidy contact (prefer mobile if two numbers)
    if "mobile_number" in df.columns and out["contact"].eq("").all():
        out["contact"] = df["mobile_number"]

    # ❺ latitude / longitude validity check
    def good_lat(x):
        try:
            f = float(x)
            return -90 <= f <= 90
        except:
            return False
    def good_lon(x):
        try:
            f = float(x)
            return -180 <= f <= 180
        except:
            return False

    out = out[ out["latitude"].apply(good_lat) & out["longitude"].apply(good_lon) ]

    # ❻ drop rows missing any ESSENTIAL field
    essentials = ["name", "type", "latitude", "longitude", "contact"]
    out = out.dropna(subset=essentials).query("name != '' and type != '' and contact != ''")

    # ❼ defaults for optional columns
    out["inventory"]           = out["inventory"].fillna("")
    out["last_updated"]        = out["last_updated"].fillna("")
    out["supported_disasters"] = out["supported_disasters"].replace("", "General")

    return out.reset_index(drop=True)

st.set_page_config(page_title="Sahara Sahaya – Disaster Relief", layout="wide")


# ---------- helper: fetch admin password safely -----------
def get_admin_pass() -> str:
    """
    Return the admin password from .streamlit/secrets.toml.
    If secrets.toml is missing, fall back to an environment
    variable ADMIN_PASS (or empty string).
    """
    try:
        return st.secrets["ADMIN_PASS"]          # requires secrets.toml
    except Exception:
        return os.getenv("ADMIN_PASS", "")


# -------------------- ADMIN LOGIN -------------------------
if "is_admin" not in st.session_state:
    st.session_state.is_admin = False

with st.sidebar.expander("🔑 Admin Login", expanded=False):
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == get_admin_pass():
            st.session_state.is_admin = True
            st.success("Admin privileges granted")
        else:
            st.error("Wrong password")

ADMIN = st.session_state.is_admin
# ----------------------------------------------------------


st.title("🛕 Sahara Sahaya")
st.markdown("#### Your Lifeline in Disasters. Locate nearby help in just a few clicks!")
st.markdown("---")

# ---------------------- LOCATION --------------------------
if "user_coordinates" not in st.session_state:
    st.session_state.user_coordinates = None

loc_mode = st.radio("📍 Choose Location Input Method:", ["Auto-detect (GPS)", "Manual Entry"])

if loc_mode == "Manual Entry":
    manual_addr = st.text_input("Enter your location (city / address)")
    if manual_addr and st.button("📌 Locate Me"):
        coords = geocode_location(manual_addr)
        if coords:
            st.session_state.user_coordinates = coords
            st.success(f"Location found: {coords}")
        else:
            st.error("❌ Location not found.")
else:
    if st.button("📡 Detect Location"):
        coords = detect_gps_location()
        if coords:
            st.session_state.user_coordinates = coords
            st.success(f"Your approximate location is: {coords}")
        else:
            st.error("❌ Could not detect location.")

# ------------------- DISASTER TYPE ------------------------
disaster_type = st.selectbox("⚠️ Select Disaster Type:",
                             ["Flood", "Earthquake", "Fire", "Cyclone", "Other"])

# ------------------ SEARCH TRIGGER ------------------------
if "search_triggered" not in st.session_state:
    st.session_state.search_triggered = False

if st.button("🔍 Search for Relief Resources"):
    if st.session_state.user_coordinates:
        st.session_state.search_triggered = True
    else:
        st.warning("📍 Please provide or detect your location first.")

# ------------------ RESULTS SECTION -----------------------
if st.session_state.search_triggered and st.session_state.user_coordinates:
    st.success(f"Showing relief resources for **{disaster_type}** near "
               f"{st.session_state.user_coordinates}")

    # Load & enrich data
    relief_df = load_relief_centers()
    relief_df["distance_km"] = relief_df.apply(
        lambda r: geodesic(st.session_state.user_coordinates,
                           (r.latitude, r.longitude)).km, axis=1)
    relief_df["time_min"]    = (relief_df["distance_km"] / 0.083).round().astype(int)
    relief_df["has_inventory"] = relief_df["inventory"].fillna("").str.strip().ne("")

    filtered_df = filter_by_disaster(relief_df, disaster_type)

    sort_choice = st.selectbox(
        "Sort centres by:",
        ("Nearest distance / time", "Inventory availability then distance"))
    if sort_choice.startswith("Inventory"):
        filtered_df = filtered_df.sort_values(["has_inventory", "distance_km"],
                                              ascending=[False, True])
    else:
        filtered_df = filtered_df.sort_values("distance_km")

    if filtered_df.empty:
        st.error("❌ No relief resources found for the selected disaster type.")
    else:
        col1, col2 = st.columns([3, 2])

        # --------- Map ----------
        with col1:
            m = create_map(st.session_state.user_coordinates, filtered_df)
            st_folium(m, width=700, height=500)

        # --------- Cards --------
        with col2:
            st.markdown("### 🧾 Nearby Relief Centres")
            for _, row in filtered_df.iterrows():
                st.markdown(f"**🏥 {row['name']}** ({row['type']})")
                st.markdown(f"- 📦 Inventory: `{row['inventory']}` *(updated {row['last_updated']})*")
                st.markdown(f"- 📍 {row.distance_km:.2f} km | 🚶 {row.time_min} min")
                phone = "".join(filter(str.isdigit, row.contact))
                contact_link = f"[{row.contact}](tel:{phone})" if phone else row.contact
                st.markdown(f"- 📞 {contact_link}")
                st.divider()

st.markdown("---")

# -------------------- ADMIN UPLOAD ------------------------
if ADMIN:
        # ---------- ADMIN UPLOAD ----------
    st.markdown("### 🛠️ Admin · Upload / Replace Relief-Centre file")
    st.caption("CSV, XLS or XLSX accepted. Column names can vary – they’ll be auto-mapped.")

    up_file = st.file_uploader("📤 Upload data file", type=["csv", "xls", "xlsx"])
    if up_file is not None:
        try:
            raw_df = read_any_file(up_file)
            clean_df = standardise_columns(raw_df)
        except Exception as e:
            st.error(f"❌ Could not read file: {e}")
            st.stop()

        if clean_df.empty:
            st.warning("⚠️ No valid records after cleaning / validation.")
        else:
            st.success(f"✅ Loaded {len(clean_df)} verified relief-centre rows.")
            st.dataframe(clean_df.head())

            if st.button("✅ Save as current dataset"):
                clean_df.to_csv("data/relief_centers.csv", index=False)
                st.success("Dataset saved! Click *Search* to reload.")


else:
    st.info("🔒 Admin features hidden – log in from sidebar.")

st.caption("Made with ❤️ Shruti Verma.")

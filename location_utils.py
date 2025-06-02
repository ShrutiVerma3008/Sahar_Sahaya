# for GPS/ manual location handeling 
# sahara_sahaya/utils/location_utils.py

import geopy
from geopy.geocoders import Nominatim
import geocoder

def geocode_location(address):
    """Convert a manually entered address to coordinates."""
    geolocator = Nominatim(user_agent="sahara_sahaya_app")
    location = geolocator.geocode(address)
    if location:
        return (location.latitude, location.longitude)
    return None

def detect_gps_location():
    """Use IP-based geolocation as a fallback for GPS."""
    g = geocoder.ip('me')
    if g.ok:
        return g.latlng
    return None

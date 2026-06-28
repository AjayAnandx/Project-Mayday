import httpx

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Depositing rime fog",
    51: "Light drizzle", 53: "Moderate drizzle", 55: "Dense drizzle",
    56: "Light freezing drizzle", 57: "Dense freezing drizzle",
    61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    66: "Light freezing rain", 67: "Heavy freezing rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow",
    77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}

WMO_EMOJI = {
    0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
    45: "🌫️", 48: "🌫️",
    51: "🌦️", 53: "🌦️", 55: "🌧️",
    56: "🌧️", 57: "🌧️",
    61: "🌧️", 63: "🌧️", 65: "🌧️",
    66: "🌧️", 67: "🌧️",
    71: "🌨️", 73: "🌨️", 75: "🌨️",
    77: "❄️",
    80: "🌦️", 81: "🌦️", 82: "🌧️",
    85: "🌨️", 86: "🌨️",
    95: "⛈️", 96: "⛈️", 99: "⛈️",
}


def geocode(location: str) -> dict | None:
    try:
        resp = httpx.get(GEOCODING_URL, params={
            "name": location, "count": 1, "language": "en", "format": "json",
        }, timeout=5)
        if resp.status_code == 200:
            results = resp.json().get("results")
            if results:
                r = results[0]
                return {
                    "lat": r["latitude"],
                    "lon": r["longitude"],
                    "name": r.get("name", location),
                    "country": r.get("country", ""),
                }
    except (httpx.HTTPError, ValueError):
        pass
    return None


def get_weather(location: str = "", lat: float | None = None, lon: float | None = None,
                days: int = 3) -> str:
    if not location and (lat is None or lon is None):
        return ""

    if lat is None or lon is None:
        geo = geocode(location)
        if not geo:
            return f"Could not find location: {location}"
        lat, lon = geo["lat"], geo["lon"]
        city = geo.get("name", location)
        country = geo.get("country", "")
    else:
        city = location or f"{lat:.1f},{lon:.1f}"
        country = ""

    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
        "timezone": "auto",
        "forecast_days": min(days, 7),
    }

    try:
        resp = httpx.get(FORECAST_URL, params=params, timeout=5)
        if resp.status_code != 200:
            return f"Weather service unavailable for {city}"
    except httpx.HTTPError:
        return f"Weather service unavailable for {city}"

    data = resp.json()
    current = data.get("current", {})
    daily = data.get("daily", {})

    location_label = city
    if country:
        location_label += f", {country}"

    lines = [f"Weather for {location_label}:", ""]

    if current:
        t = current.get("temperature_2m")
        feels = current.get("apparent_temperature")
        w_code = current.get("weather_code")
        wind = current.get("wind_speed_10m")
        hum = current.get("relative_humidity_2m")
        cond = WMO_CODES.get(w_code, "")
        emoji = WMO_EMOJI.get(w_code, "")

        parts = []
        if t is not None:
            parts.append(f"Temperature: {t:.0f}°C")
        if feels is not None and t is not None and abs(feels - t) > 2:
            parts.append(f"feels like {feels:.0f}°C")
        if cond:
            parts.append(cond)
        if hum is not None:
            parts.append(f"Humidity: {hum:.0f}%")
        if wind is not None:
            parts.append(f"Wind: {wind:.0f} km/h")
        lines.append(f"Current: {', '.join(parts)} {emoji}".strip())

    if daily.get("time"):
        lines.append("")
        lines.append("Forecast:")
        for i in range(min(len(daily["time"]), days)):
            date = daily["time"][i]
            t_max = daily["temperature_2m_max"][i]
            t_min = daily["temperature_2m_min"][i]
            precip = daily["precipitation_sum"][i]
            w_code = daily["weather_code"][i]
            emoji = WMO_EMOJI.get(w_code, "")
            precip_str = f" {precip:.0f}mm" if precip and precip > 0 else ""
            lines.append(f"  {date}: {t_min:.0f}-{t_max:.0f}°C {emoji}{precip_str}")

    return "\n".join(lines)

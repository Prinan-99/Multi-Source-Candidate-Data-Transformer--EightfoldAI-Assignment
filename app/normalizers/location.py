"""
Normalise location strings into {city, region, country (ISO 3166-1 alpha-2)}.
We use a lightweight lookup table for the most common cases; anything unknown
is left in the city field rather than invented.
"""

from __future__ import annotations

# Common country name / alias → ISO 3166-1 alpha-2
_COUNTRY_MAP: dict[str, str] = {
    "india": "IN", "in": "IN",
    "united states": "US", "usa": "US", "us": "US", "united states of america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "canada": "CA", "ca": "CA",
    "australia": "AU", "au": "AU",
    "germany": "DE", "de": "DE",
    "france": "FR", "fr": "FR",
    "singapore": "SG", "sg": "SG",
    "dubai": "AE", "uae": "AE", "united arab emirates": "AE",
    "netherlands": "NL", "nl": "NL",
    "japan": "JP", "jp": "JP",
    "china": "CN", "cn": "CN",
    "brazil": "BR", "br": "BR",
    "mexico": "MX", "mx": "MX",
    "south korea": "KR", "korea": "KR",
    "sweden": "SE", "norway": "NO", "denmark": "DK",
    "switzerland": "CH", "austria": "AT",
    "spain": "ES", "portugal": "PT", "italy": "IT",
    "israel": "IL", "new zealand": "NZ", "nz": "NZ",
}

# Indian state abbreviations / names → region code
_INDIA_STATES: dict[str, str] = {
    "tamil nadu": "TN", "tn": "TN",
    "maharashtra": "MH", "mh": "MH",
    "karnataka": "KA", "ka": "KA",
    "delhi": "DL", "new delhi": "DL",
    "telangana": "TS", "ts": "TS",
    "andhra pradesh": "AP", "ap": "AP",
    "kerala": "KL", "kl": "KL",
    "gujarat": "GJ", "gj": "GJ",
    "rajasthan": "RJ", "rj": "RJ",
    "west bengal": "WB", "wb": "WB",
    "uttar pradesh": "UP", "up": "UP",
    "punjab": "PB", "pb": "PB",
    "haryana": "HR", "hr": "HR",
}

# Well-known cities → (city, region, country_alpha2)
_CITY_LOOKUP: dict[str, tuple[str, str | None, str]] = {
    "bangalore": ("Bangalore", "KA", "IN"),
    "bengaluru": ("Bangalore", "KA", "IN"),
    "mumbai": ("Mumbai", "MH", "IN"),
    "delhi": ("Delhi", "DL", "IN"),
    "new delhi": ("New Delhi", "DL", "IN"),
    "hyderabad": ("Hyderabad", "TS", "IN"),
    "chennai": ("Chennai", "TN", "IN"),
    "pune": ("Pune", "MH", "IN"),
    "kolkata": ("Kolkata", "WB", "IN"),
    "ahmedabad": ("Ahmedabad", "GJ", "IN"),
    "coimbatore": ("Coimbatore", "TN", "IN"),
    "san francisco": ("San Francisco", "CA", "US"),
    "new york": ("New York", "NY", "US"),
    "seattle": ("Seattle", "WA", "US"),
    "austin": ("Austin", "TX", "US"),
    "chicago": ("Chicago", "IL", "US"),
    "london": ("London", "ENG", "GB"),
    "toronto": ("Toronto", "ON", "CA"),
    "singapore": ("Singapore", None, "SG"),
    "berlin": ("Berlin", None, "DE"),
    "sydney": ("Sydney", "NSW", "AU"),
    "melbourne": ("Melbourne", "VIC", "AU"),
}


def parse_location(raw: str | None) -> dict[str, str | None]:
    """
    Parse a free-text location string into {city, region, country}.
    Best-effort: unknown parts are left None rather than invented.
    """
    if not raw:
        return {"city": None, "region": None, "country": None}

    parts = [p.strip() for p in raw.split(",")]
    result: dict[str, str | None] = {"city": None, "region": None, "country": None}

    # Handle space-separated "City Country" (no comma), e.g. "Chennai India"
    if len(parts) == 1 and " " in parts[0]:
        words = parts[0].split()
        # Check if last word is a known country
        last_word = words[-1].lower()
        if last_word in _COUNTRY_MAP:
            result["country"] = _COUNTRY_MAP[last_word]
            city_candidate = " ".join(words[:-1])
            city_lower = city_candidate.lower()
            if city_lower in _CITY_LOOKUP:
                c, r, co = _CITY_LOOKUP[city_lower]
                result["city"] = c
                result["region"] = r
                if not result["country"]:
                    result["country"] = co
            else:
                result["city"] = city_candidate
            return result

    # Try city lookup on the first part
    first_lower = parts[0].lower() if parts else ""
    if first_lower in _CITY_LOOKUP:
        city, region, country = _CITY_LOOKUP[first_lower]
        result["city"] = city
        result["region"] = region
        result["country"] = country
        return result

    # Try to resolve country from the last part
    if len(parts) >= 2:
        country_raw = parts[-1].lower()
        if country_raw in _COUNTRY_MAP:
            result["country"] = _COUNTRY_MAP[country_raw]
        result["city"] = parts[0] if parts[0] else None

    elif len(parts) == 1:
        # Could be just a country
        single = parts[0].lower()
        if single in _COUNTRY_MAP:
            result["country"] = _COUNTRY_MAP[single]
        else:
            result["city"] = parts[0]

    return result

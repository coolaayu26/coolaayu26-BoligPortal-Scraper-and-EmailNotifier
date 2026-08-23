"""
BoligPortal scraper v2 — reads the site's embedded JSON data store
(<script id="store" type="application/json">) instead of parsing
hashed CSS classes. This is the same JSON React/Next.js uses to
render the page, so it already contains every field per listing
(rooms, size, rent, deposit, available-from date, elevator,
furnished, shareable, balcony, parking, postal code, district...).
No need to visit each ad's individual page.

Usage (run from the repo root, or anywhere — paths below are relative
to this file's location):
    python3 scrape_and_filter.py
"""

import json
import re
import time
from datetime import datetime, date
from pathlib import Path

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}
PAGE_SIZE = 18  # fixed by BoligPortal's site, not configurable

HOUSING_TYPE_MAP = {
    "Apartment": ["rental_apartment"],
    "Townhouse": ["rental_townhouse"],
    "House": [
        "rental_house", "rental_villa", "rental_detached_single_family_house",
        "rental_parcel_house", "rental_double_house", "rental_half_double_house",
        "rental_multi_family_house", "rental_small_house", "rental_city_house",
    ],
    "Room": ["rental_room"],
}


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def fetch_store(url: str) -> dict:
    """Fetch a BoligPortal page and return its embedded JSON store."""
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    match = re.search(
        r'<script id="store" type="application/json">(.*?)</script>',
        resp.text, re.S,
    )
    if not match:
        raise RuntimeError(f"No JSON store found on page: {url}")
    return json.loads(match.group(1))


def flatten_ad(raw: dict) -> dict:
    features = raw.get("features") or {}
    location = raw.get("location") or {}
    images = raw.get("images") or []
    return {
        "id": raw.get("id"),
        "url": "https://www.boligportal.dk" + raw["url"] if raw.get("url") else None,
        "image_url": images[0]["url"] if images else None,
        "category": raw.get("category"),
        "title": raw.get("title"),
        "street_name": raw.get("street_name"),
        "street_number": raw.get("street_number"),
        "postal_code": raw.get("postal_code"),
        "city_area": raw.get("city_area"),
        "lat": location.get("lat"),
        "lon": location.get("lng"),
        "rooms": raw.get("rooms"),
        "size_m2": raw.get("size_m2"),
        "monthly_rent": raw.get("monthly_rent"),
        "monthly_rent_extra_costs": raw.get("monthly_rent_extra_costs"),
        "total_monthly_cost": (raw.get("monthly_rent") or 0) + (raw.get("monthly_rent_extra_costs") or 0),
        "deposit": raw.get("deposit"),
        "prepaid_rent": raw.get("prepaid_rent"),
        "rental_period": raw.get("rental_period"),  # 0 = Unlimited, else months
        "available_from": raw.get("available_from"),
        "created": raw.get("created"),
        "elevator": features.get("elevator"),
        "furnished": features.get("furnished"),
        "shareable": features.get("shareable"),
        "pet_friendly": features.get("pet_friendly"),
        "student_only": features.get("student_only"),
        "balcony": features.get("balcony"),
        "parking": features.get("parking"),
    }


def scrape_all(main_url: str, pages: int, progress_callback=None) -> pd.DataFrame:
    base_url = main_url.split("?")[0]
    all_ads = {}

    for i in range(pages):
        offset = PAGE_SIZE * i
        url = f"{base_url}?offset={offset}"
        print(f"Fetching page {i + 1}/{pages}: {url}")
        store = fetch_store(url)
        results = store["props"]["page_props"]["results"]
        if not results:
            print("No more results — stopping early.")
            if progress_callback:
                progress_callback(i + 1, pages, len(all_ads), done=True)
            break
        for raw in results:
            flat = flatten_ad(raw)
            all_ads[flat["id"]] = flat
        if progress_callback:
            progress_callback(i + 1, pages, len(all_ads), done=False)
        time.sleep(1)  # be polite between requests

    print(f"{len(all_ads)} unique listings scraped.")
    return pd.DataFrame(all_ads.values())


def apply_filters(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    out = df.copy()

    if cfg.get("MAX_DAYS_SINCE_CREATION") is not None:
        cutoff_days = cfg["MAX_DAYS_SINCE_CREATION"]
        created = pd.to_datetime(out["created"], utc=True, format="ISO8601")
        age_days = (pd.Timestamp.now(tz="UTC") - created).dt.days
        out = out[age_days <= cutoff_days]

    if cfg.get("USE_ZIPCODE_FILTER") == "yes":
        zips = out["postal_code"].astype(float).astype("Int64")
        ftype = cfg.get("ZIPCODE_FILTER_TYPE")
        if ftype == "list" and cfg.get("ZIPCODE_LIST_FILTER"):
            out = out[zips.isin(cfg["ZIPCODE_LIST_FILTER"])]
        elif ftype == "range" and cfg.get("ZIPCODE_RANGE_FILTER"):
            lo, hi = cfg["ZIPCODE_RANGE_FILTER"]
            out = out[(zips >= lo) & (zips <= hi)]
        if cfg.get("ZIPCODE_EXCLUDE_FILTER"):
            out = out[~zips.isin(cfg["ZIPCODE_EXCLUDE_FILTER"])]

    if cfg.get("USE_DISTRICT_FILTER") == "yes" and cfg.get("DISTRICT_FILTER"):
        out = out[out["city_area"].isin(cfg["DISTRICT_FILTER"])]

    if cfg.get("USE_HOUSING_TYPE_FILTER") == "yes" and cfg.get("HOUSING_TYPE_FILTER"):
        allowed_categories = set()
        for t in cfg["HOUSING_TYPE_FILTER"]:
            allowed_categories.update(HOUSING_TYPE_MAP.get(t, []))
        out = out[out["category"].isin(allowed_categories)]

    if cfg.get("SIZE_FILTER"):
        lo, hi = cfg["SIZE_FILTER"]
        out = out[(out["size_m2"] >= lo) & (out["size_m2"] <= hi)]

    if cfg.get("NUMBER_OF_ROOMS_FILTER"):
        lo, hi = cfg["NUMBER_OF_ROOMS_FILTER"]
        out = out[(out["rooms"] >= lo) & (out["rooms"] <= hi)]

    if cfg.get("RENTAL_PERIOD_FILTER"):
        wanted = set(cfg["RENTAL_PERIOD_FILTER"])
        def period_label(months):
            if months == 0:
                return "Unlimited"
            elif months < 24:
                return "12-23 months"
            else:
                return "24+ months"
        out = out[out["rental_period"].apply(period_label).isin(wanted)]

    if cfg.get("AVAILABLE_FROM_RANGE"):
        lo, hi = cfg["AVAILABLE_FROM_RANGE"]
        lo_date = datetime.strptime(lo, "%m/%d/%Y").date()
        hi_date = datetime.strptime(hi, "%m/%d/%Y").date()
        avail = pd.to_datetime(out["available_from"]).dt.date
        out = out[(avail >= lo_date) & (avail <= hi_date)]

    if cfg.get("TOTAL_RENT_MAX") is not None:
        out = out[out["total_monthly_cost"] <= cfg["TOTAL_RENT_MAX"]]

    if cfg.get("DEPOSIT_MAX") is not None:
        max_deposit_kr = cfg["DEPOSIT_MAX"] * out["monthly_rent"]
        out = out[out["deposit"] <= max_deposit_kr]

    if cfg.get("PREPAID_RENT") == "yes" and cfg.get("PREPAID_RENT_MAX") is not None:
        max_prepaid_kr = cfg["PREPAID_RENT_MAX"] * out["monthly_rent"]
        out = out[out["prepaid_rent"] <= max_prepaid_kr]

    bool_filters = {
        "FURNISHED": "furnished",
        "SHAREABLE": "shareable",
        "PETS_ALLOWED": "pet_friendly",
        "HAS_ELEVATOR": "elevator",
        "STUDENTS_ONLY": "student_only",
        "HAS_BALCONY": "balcony",
        "HAS_PARKING": "parking",
    }
    for cfg_key, col in bool_filters.items():
        allowed = cfg.get(cfg_key)
        if allowed is not None and set(allowed) != {0, 1}:
            wanted_bools = {bool(v) for v in allowed}
            out = out[out[col].isin(wanted_bools)]

    return out


def main():
    here = Path(__file__).parent
    scraper_cfg = load_config(here / "config" / "scraper_config.json")
    filter_cfg = load_config(here / "config" / "filter_config.json")

    df = scrape_all(scraper_cfg["MAIN_URL"], scraper_cfg["RESULTS_PAGES"])

    raw_output = here / "data" / "bp_ads_v2.csv"
    raw_output.parent.mkdir(exist_ok=True)
    df.to_csv(raw_output, index=False)
    print(f"Raw data saved to {raw_output}")

    filtered = apply_filters(df, filter_cfg)
    print(f"{len(filtered)} listings match your filters.")

    filtered_output = here / "data" / "filter_output_v2.xlsx"
    filtered.to_excel(filtered_output, index=False)
    print(f"Filtered results saved to {filtered_output}")


if __name__ == "__main__":
    main()

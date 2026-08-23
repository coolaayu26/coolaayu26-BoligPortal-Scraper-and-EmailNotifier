"""
BoligPortal Finder — graphical UI

Run with:
    streamlit run boligportal_app.py

Requires: streamlit, pandas, requests, openpyxl
    pip install streamlit pandas requests openpyxl

Must sit in the same folder as scrape_and_filter.py (same repo root
as config/ and data/).
"""

import io
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from scrape_and_filter import scrape_all, apply_filters, load_config, HOUSING_TYPE_MAP

st.set_page_config(page_title="BoligPortal Finder", page_icon="🏠", layout="wide")
st.title("🏠 BoligPortal Finder")

HERE = Path(__file__).parent
SCRAPER_CFG_PATH = HERE / "config" / "scraper_config.json"
FILTER_CFG_PATH = HERE / "config" / "filter_config.json"

# Load existing config files as starting defaults, so the sliders open
# wherever you last left the JSON files.
scraper_defaults = load_config(SCRAPER_CFG_PATH)
filter_defaults = load_config(FILTER_CFG_PATH)


def parse_date(s, fallback):
    try:
        m, d, y = s.split("/")
        return date(int(y), int(m), int(d))
    except Exception:
        return fallback


with st.sidebar:
    st.header("Search")
    main_url = st.text_input("BoligPortal search URL", scraper_defaults["MAIN_URL"])
    pages = st.slider("Pages to scrape (18 listings each)", 1, 100, scraper_defaults["RESULTS_PAGES"])

    st.header("Filters")

    max_days = st.slider("Max days since posted", 1, 60, filter_defaults.get("MAX_DAYS_SINCE_CREATION", 14))

    zip_default = ", ".join(str(z) for z in filter_defaults.get("ZIPCODE_LIST_FILTER", []))
    zip_text = st.text_input("Zip codes (comma-separated, blank = no filter)", zip_default)

    housing_types = st.multiselect(
        "Housing type", list(HOUSING_TYPE_MAP.keys()),
        default=filter_defaults.get("HOUSING_TYPE_FILTER", ["Apartment"]),
    )

    size_default = tuple(filter_defaults.get("SIZE_FILTER", [0, 300]))
    size_range = st.slider("Size (m²)", 0, 400, size_default)

    rooms_default = tuple(int(x) for x in filter_defaults.get("NUMBER_OF_ROOMS_FILTER", [1, 10]))
    rooms_range = st.slider("Rooms", 1, 12, rooms_default)

    rent_max = st.number_input("Max total monthly cost (kr)", value=int(filter_defaults.get("TOTAL_RENT_MAX", 20000)), step=500)

    deposit_max = st.number_input("Max deposit (months' rent)", value=float(filter_defaults.get("DEPOSIT_MAX", 3)), step=0.5)
    prepaid_max = st.number_input("Max prepaid rent (months)", value=float(filter_defaults.get("PREPAID_RENT_MAX", 3)), step=0.5)

    rental_period_options = ["Unlimited", "12-23 months", "24+ months"]
    rental_periods = st.multiselect("Rental period", rental_period_options, default=filter_defaults.get("RENTAL_PERIOD_FILTER", ["Unlimited"]))

    avail_default = filter_defaults.get("AVAILABLE_FROM_RANGE", ["01/01/2026", "12/31/2026"])
    avail_lo, avail_hi = st.date_input(
        "Available from — range",
        value=(parse_date(avail_default[0], date.today()), parse_date(avail_default[1], date.today())),
    )

    st.subheader("Must-haves")
    elevator_required = st.checkbox("Elevator required", value=filter_defaults.get("HAS_ELEVATOR") == [1])
    unfurnished_only = st.checkbox("Must be unfurnished", value=filter_defaults.get("FURNISHED") == [0])
    no_sharing = st.checkbox("No shared/roommate listings", value=filter_defaults.get("SHAREABLE") == [0])
    pets_ok_only = st.checkbox("Pets allowed only", value=filter_defaults.get("PETS_ALLOWED") == [1])
    balcony_required = st.checkbox("Balcony required", value=filter_defaults.get("HAS_BALCONY") == [1])
    parking_required = st.checkbox("Parking required", value=filter_defaults.get("HAS_PARKING") == [1])

    run = st.button("🔍 Scrape & Filter", type="primary", width="stretch")


def build_filter_config():
    zips = [int(z.strip()) for z in zip_text.split(",") if z.strip()]
    return {
        "MAX_DAYS_SINCE_CREATION": max_days,
        "USE_ZIPCODE_FILTER": "yes" if zips else "no",
        "ZIPCODE_FILTER_TYPE": "list",
        "ZIPCODE_LIST_FILTER": zips,
        "ZIPCODE_EXCLUDE_FILTER": [],
        "USE_DISTRICT_FILTER": "no",
        "USE_HOUSING_TYPE_FILTER": "yes" if housing_types else "no",
        "HOUSING_TYPE_FILTER": housing_types,
        "SIZE_FILTER": list(size_range),
        "NUMBER_OF_ROOMS_FILTER": list(rooms_range),
        "RENTAL_PERIOD_FILTER": rental_periods,
        "AVAILABLE_FROM_RANGE": [avail_lo.strftime("%m/%d/%Y"), avail_hi.strftime("%m/%d/%Y")],
        "TOTAL_RENT_MAX": rent_max,
        "DEPOSIT_MAX": deposit_max,
        "PREPAID_RENT": "yes",
        "PREPAID_RENT_MAX": prepaid_max,
        "FURNISHED": [0] if unfurnished_only else [0, 1],
        "SHAREABLE": [0] if no_sharing else [0, 1],
        "PETS_ALLOWED": [1] if pets_ok_only else [0, 1],
        "HAS_ELEVATOR": [1] if elevator_required else [0, 1],
        "STUDENTS_ONLY": [0, 1],
        "HAS_BALCONY": [1] if balcony_required else [0, 1],
        "HAS_PARKING": [1] if parking_required else [0, 1],
    }


if run:
    progress_bar = st.progress(0, text=f"Starting scrape of up to {pages} page(s)...")
    status = st.empty()

    def update_progress(current_page, total_pages, listings_so_far, done):
        pct = current_page / total_pages
        progress_bar.progress(pct, text=f"Page {current_page}/{total_pages} — {listings_so_far} listings scraped so far")
        if done:
            status.info("Reached the end of available results early.")

    df = scrape_all(main_url, pages, progress_callback=update_progress)

    progress_bar.progress(1.0, text=f"Done — {len(df)} unique listings scraped.")
    with st.spinner("Applying filters..."):
        st.session_state["raw_df"] = df
        st.session_state["filtered_df"] = apply_filters(df, build_filter_config())
    progress_bar.empty()
    status.empty()

raw_df = st.session_state.get("raw_df")
filtered_df = st.session_state.get("filtered_df")

if filtered_df is None:
    st.info("Set your filters in the sidebar and click **Scrape & Filter** to get started.")
else:
    st.subheader(f"{len(filtered_df)} matching listings (out of {len(raw_df)} scraped)")

    if len(filtered_df):
        tab_cards, tab_table, tab_map = st.tabs(["🖼️ Cards", "📋 Table", "🗺️ Map"])

        with tab_cards:
            for _, row in filtered_df.sort_values("monthly_rent").iterrows():
                with st.container(border=True):
                    cols = st.columns([1, 3])
                    with cols[0]:
                        if row.get("image_url"):
                            st.image(row["image_url"], width="stretch")
                    with cols[1]:
                        st.markdown(f"### [{row['title']}]({row['url']})")
                        st.write(f"{row['street_name']} {row['street_number']}, {row['postal_code']} {row['city_area']}")
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Rent/mo", f"{row['monthly_rent']:,.0f} kr")
                        m2.metric("Size", f"{row['size_m2']:.0f} m²")
                        m3.metric("Rooms", f"{row['rooms']:.0f}")
                        m4.metric("Available", row["available_from"])
                        badges = []
                        if row["elevator"]:
                            badges.append("🛗 Elevator")
                        if row["balcony"]:
                            badges.append("🌿 Balcony")
                        if row["parking"]:
                            badges.append("🚗 Parking")
                        if row["pet_friendly"]:
                            badges.append("🐾 Pets OK")
                        st.write(" · ".join(badges) if badges else "—")

        with tab_table:
            st.dataframe(
                filtered_df[[
                    "title", "street_name", "postal_code", "city_area", "rooms", "size_m2",
                    "monthly_rent", "available_from", "elevator", "furnished", "url",
                ]],
                width="stretch",
                column_config={"url": st.column_config.LinkColumn("Link")},
            )

        with tab_map:
            if "lat" in filtered_df.columns and "lon" in filtered_df.columns:
                map_df = filtered_df.dropna(subset=["lat", "lon"])
                if len(map_df):
                    st.map(map_df[["lat", "lon"]])
                else:
                    st.write("No location data available for these listings.")
            else:
                st.warning(
                    "This data has no location columns — you're likely running an older "
                    "scrape_and_filter.py. Replace it with the latest version and re-scrape."
                )

        buffer = io.BytesIO()
        filtered_df.to_excel(buffer, index=False)
        st.download_button(
            "⬇️ Download filtered results (.xlsx)",
            data=buffer.getvalue(),
            file_name="filtered_apartments.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.warning("No listings matched your filters. Try loosening a constraint in the sidebar and re-running.")

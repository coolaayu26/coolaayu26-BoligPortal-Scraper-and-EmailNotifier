# BoligPortal Apartment Finder

Scrapes BoligPortal.dk rental listings, filters them against custom
criteria (location, size, rent, elevator, etc.), and can automatically
email you when new matches appear.

## What's in here

- **`scrape_and_filter.py`** — core logic. Reads BoligPortal's search
  results pages, pulls listing data from the page's embedded JSON
  (rooms, size, rent, elevator, deposit, available-from date, etc.),
  and filters it against your criteria.
- **`config/scraper_config.json`** — which BoligPortal search URL to
  scrape and how many pages.
- **`config/filter_config.json`** — your filter criteria: zip codes,
  size range, room count, max rent, elevator/furnished/shareable
  requirements, and more.
- **`boligportal_app.py`** — a Streamlit web UI for browsing results
  with sliders/checkboxes instead of editing JSON by hand. Run with
  `streamlit run boligportal_app.py`.
- **`daily_notifier.py`** — scrapes, filters, tracks which listings
  are new since the last run (via `data/seen_ids.json`), and emails a
  digest with a ready-to-send landlord inquiry message for each new
  match. Requires `email_config.json` (see
  `email_config.example.json` — never commit the real one).
- **`.github/workflows/notifier.yml`** — runs `daily_notifier.py` on
  a schedule via GitHub Actions, so it works without your laptop
  needing to be on. Configure via repo Secrets
  (`GMAIL_SENDER`, `GMAIL_APP_PASSWORD`, `GMAIL_RECIPIENTS_JSON`).

## Setup

```bash
pip install pandas requests openpyxl streamlit
cp email_config.example.json email_config.json  # then fill in your real credentials
python3 scrape_and_filter.py       # one-off scrape + filter -> data/filter_output_v2.xlsx
python3 daily_notifier.py          # scrape + filter + email new matches
streamlit run boligportal_app.py   # interactive browser UI
```

## Notes

- BoligPortal's terms ask that data not be collected in a "regular,
  systematic" way without permission — be mindful of scrape frequency.
- Zip-code filtering is a proxy for commute time, not exact walking
  distance — worth eyeballing borderline matches on a map.

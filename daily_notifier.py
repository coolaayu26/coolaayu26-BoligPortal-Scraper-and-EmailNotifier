"""
daily_notifier.py — runs the scrape+filter pipeline, tracks which
listings are new since the last run, and emails you a morning digest
with a ready-to-send landlord message for each new match.

Intended to run a few times a day via a scheduled job (see the
accompanying launchd instructions) rather than manually. Duplicate
listings are never re-emailed — every listing ID is tracked in
data/seen_ids.json, so only genuinely new matches trigger an email
on any given run.

Requires an email_config.json in this same folder (see
email_config.example.json for the format) — this file is NOT provided
for you since it needs your real email credentials. Never commit it
to a public repo.
"""

import io
import json
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from scrape_and_filter import scrape_all, apply_filters, load_config

HERE = Path(__file__).parent
SEEN_IDS_PATH = HERE / "data" / "seen_ids.json"
EMAIL_CONFIG_PATH = HERE / "email_config.json"


def load_seen_ids() -> set:
    if SEEN_IDS_PATH.exists():
        return set(json.loads(SEEN_IDS_PATH.read_text()))
    return set()


def save_seen_ids(ids: set):
    SEEN_IDS_PATH.parent.mkdir(exist_ok=True)
    SEEN_IDS_PATH.write_text(json.dumps(sorted(ids)))


def generate_landlord_message(row) -> str:
    """A friendly, professional inquiry message tailored to one listing."""
    address = f"{row['street_name']} {row['street_number']}, {row['postal_code']} {row['city_area']}"
    return (
        f"Hi,\n\n"
        f"I'm writing to express interest in your listing at {address} "
        f"({row['rooms']:.0f} rooms, {row['size_m2']:.0f} m², {row['monthly_rent']:,.0f} kr/month).\n\n"
        f"A bit about us: I recently relocated to Copenhagen for a role at Templafy, and I'm looking "
        f"for a place to settle into long-term with my partner. We're a quiet, professional household, "
        f"financially stable, and happy to provide references and proof of income. We're able to move "
        f"in from {row['available_from']}.\n\n"
        f"Would it be possible to arrange a viewing? I'm glad to work around your schedule, including "
        f"evenings or weekends.\n\n"
        f"Thank you for your time — I look forward to hearing from you.\n\n"
        f"Best regards,\n"
        f"Aayush"
    )


def _clean_credential(value: str) -> str:
    """Strip regular and non-breaking spaces (\\xa0) that commonly get
    pasted in from Google's App Password page, which displays the
    password grouped as 'xxxx xxxx xxxx xxxx'."""
    return value.replace("\xa0", "").replace(" ", "").strip()


def _normalize_recipients(recipient) -> list:
    """Accepts either a single email string or a list of them."""
    if isinstance(recipient, str):
        return [_clean_credential(recipient)]
    return [_clean_credential(r) for r in recipient]


def send_email(cfg, subject, body_text, attachment_bytes=None, attachment_name=None):
    recipients = _normalize_recipients(cfg["recipient"])
    msg = MIMEMultipart()
    msg["From"] = cfg["sender"]
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    if attachment_bytes is not None:
        part = MIMEApplication(attachment_bytes, Name=attachment_name)
        part["Content-Disposition"] = f'attachment; filename="{attachment_name}"'
        msg.attach(part)

    with smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"]) as server:
        server.login(_clean_credential(cfg["sender"]), _clean_credential(cfg["app_password"]))
        server.sendmail(cfg["sender"], recipients, msg.as_string())


def build_digest_body(new_matches) -> str:
    lines = [f"{len(new_matches)} new listing(s) matched your filters this morning:\n"]
    for _, row in new_matches.iterrows():
        lines.append(f"— {row['title']}")
        lines.append(f"  {row['rooms']:.0f} rm, {row['size_m2']:.0f} m², {row['monthly_rent']:,.0f} kr/mo, available {row['available_from']}")
        lines.append(f"  {row['url']}")
        lines.append("")
        lines.append("  Suggested message to the landlord:")
        lines.append("  " + generate_landlord_message(row).replace("\n", "\n  "))
        lines.append("\n" + ("-" * 50) + "\n")
    return "\n".join(lines)


def main():
    scraper_cfg = load_config(HERE / "config" / "scraper_config.json")
    filter_cfg = load_config(HERE / "config" / "filter_config.json")

    if not EMAIL_CONFIG_PATH.exists():
        print(f"Missing {EMAIL_CONFIG_PATH} — copy email_config.example.json and fill in your details.")
        return

    email_cfg = load_config(EMAIL_CONFIG_PATH)

    df = scrape_all(scraper_cfg["MAIN_URL"], scraper_cfg["RESULTS_PAGES"])
    filtered = apply_filters(df, filter_cfg)

    seen_ids = load_seen_ids()
    new_matches = filtered[~filtered["id"].isin(seen_ids)]

    if len(new_matches) == 0:
        print("No new matches today — no email sent.")
        return

    buffer = io.BytesIO()
    filtered.to_excel(buffer, index=False)

    send_email(
        email_cfg,
        subject=f"\U0001F3E0 {len(new_matches)} new apartment match(es) this morning",
        body_text=build_digest_body(new_matches),
        attachment_bytes=buffer.getvalue(),
        attachment_name="filtered_apartments.xlsx",
    )

    save_seen_ids(seen_ids | set(filtered["id"]))
    print(f"Emailed {len(new_matches)} new match(es).")


if __name__ == "__main__":
    main()
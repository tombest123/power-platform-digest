"""
Power Platform Daily News Digest — GitHub Actions Runner
This script is triggered by GitHub Actions on a schedule.
Secrets are read from environment variables set in GitHub.
"""

import anthropic
import smtplib
import json
import logging
import os
import re
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

# Read secrets from environment variables (set in GitHub Actions)
ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

SYSTEM_PROMPT = """You are a Power Platform news analyst. Search the web for the latest Power Platform news.

Cover: Microsoft Power Platform blog, Learn release notes, Power Automate, Power Apps, Power BI, Copilot Studio, Power Pages, AI Builder, community highlights, upcoming events and webinars.

CRITICAL INSTRUCTIONS:
- Your ENTIRE response must be a single valid JSON object. Nothing before it, nothing after it.
- No intro text, no explanations, no markdown, no backticks, no commentary whatsoever.
- Start your response with { and end with }
- If little news exists from the last 24 hours, use the most recent news from the past week.

JSON structure (return exactly this shape):
{
  "date": "YYYY-MM-DD",
  "summary": "2-3 sentence executive summary",
  "items": [
    {
      "category": "Copilot & AI|Power Automate|Power Apps|Power BI|Events|General",
      "title": "short headline",
      "detail": "2-3 sentence description and why it matters",
      "source": "source name",
      "url": "https://... or empty string",
      "importance": "high|medium|low"
    }
  ]
}

Return 6-10 items. High importance first."""


def fetch_digest() -> dict:
    logging.info("Fetching Power Platform digest from Claude...")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": "Fetch today's Power Platform news digest."}],
    )

    all_text = " ".join(
        b.text for b in response.content if hasattr(b, "text") and b.text
    ).strip()

    if not all_text:
        raise ValueError("No text in Claude response.")

    logging.info("Response preview: %s", all_text[:300])

    match = re.search(r'\{.*\}', all_text, re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in response: {all_text[:300]}")

    return json.loads(match.group(0).strip())


def build_html_email(digest: dict) -> str:
    importance_colors = {"high": "#E24B4A", "medium": "#EF9F27", "low": "#888780"}
    category_colors = {
        "Copilot & AI":   "#7F77DD",
        "Power Automate": "#1D9E75",
        "Power Apps":     "#378ADD",
        "Power BI":       "#EF9F27",
        "Events":         "#D85A30",
        "General":        "#888780",
    }

    items_html = ""
    for item in digest.get("items", []):
        dot_color   = importance_colors.get(item.get("importance", "low"), "#888780")
        badge_color = category_colors.get(item.get("category", "General"), "#888780")
        url_html    = (f'<a href="{item["url"]}" style="color:#378ADD;font-size:12px;">Read more ↗</a>'
                       if item.get("url") else "")
        items_html += f"""
        <div style="border:1px solid #e5e5e5;border-radius:10px;padding:14px 16px;margin-bottom:10px;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:{dot_color};"></span>
            <span style="background:{badge_color}22;color:{badge_color};font-size:11px;font-weight:600;
                         padding:2px 8px;border-radius:99px;">{item.get('category','General')}</span>
            <span style="font-size:11px;color:#888;">{item.get('source','')}</span>
          </div>
          <p style="margin:0 0 6px;font-size:14px;font-weight:600;color:#111;">{item.get('title','')}</p>
          <p style="margin:0 0 8px;font-size:13px;color:#555;line-height:1.6;">{item.get('detail','')}</p>
          {url_html}
        </div>"""

    date_str = digest.get("date", datetime.today().strftime("%Y-%m-%d"))
    summary  = digest.get("summary", "")

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;
             margin:0 auto;padding:24px 16px;background:#fff;color:#111;">
  <h2 style="font-size:20px;font-weight:600;margin:0 0 4px;">⚡ Power Platform digest</h2>
  <p style="font-size:13px;color:#888;margin:0 0 20px;">{date_str}</p>

  <div style="background:#f7f7f7;border-radius:10px;padding:14px 16px;margin-bottom:20px;">
    <p style="font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;
               letter-spacing:.06em;margin:0 0 8px;">Today's summary</p>
    <p style="font-size:14px;line-height:1.7;margin:0;">{summary}</p>
  </div>

  {items_html}

  <p style="font-size:11px;color:#bbb;margin-top:24px;text-align:center;">
    Sent by your Power Platform News Agent · {datetime.now().strftime("%H:%M")} UTC
  </p>
</body></html>"""


def send_email(subject: str, html_body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_ADDRESS
    msg["To"]      = GMAIL_ADDRESS
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, GMAIL_ADDRESS, msg.as_string())


if __name__ == "__main__":
    logging.info("Starting Power Platform digest run...")
    digest   = fetch_digest()
    html     = build_html_email(digest)
    date_str = digest.get("date", datetime.today().strftime("%Y-%m-%d"))
    subject  = f"⚡ Power Platform digest — {date_str}"
    send_email(subject, html)
    logging.info("Digest sent successfully to %s", GMAIL_ADDRESS)

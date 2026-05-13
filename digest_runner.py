"""
Power Platform Daily News Digest — GitHub Actions Runner
Runs Monday, Wednesday, Friday at 8 AM UTC.
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

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GMAIL_ADDRESS      = os.environ["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = os.environ["GMAIL_APP_PASSWORD"]

# Work out the lookback window label for the prompt
DAY_OF_WEEK = datetime.utcnow().weekday()  # 0=Mon, 2=Wed, 4=Fri
if DAY_OF_WEEK == 0:
    LOOKBACK = "Friday, Saturday, and Sunday (the past weekend)"
elif DAY_OF_WEEK == 2:
    LOOKBACK = "Monday and Tuesday"
else:
    LOOKBACK = "Wednesday and Thursday"

SYSTEM_PROMPT = f"""You are a Power Platform news analyst. Search the web for the latest Power Platform news and learning materials published since {LOOKBACK}.

PRIORITY TOPICS (always surface these first, include the most items here):
1. Copilot Studio and AI agents
2. Canvas Apps and Model-driven Apps
3. Power Automate
4. Dataverse
5. Security and governance

STANDARD TOPICS (include if there is notable news, below priority content):
- Power BI
- Power Pages
- Events and community

ADDITIONAL SOURCES TO CHECK:
- LinkedIn posts from Microsoft Power Platform MVPs and the official Microsoft Power Platform LinkedIn page
- Microsoft Learn release notes and documentation updates
- Microsoft Power Platform blog (powerplatform.microsoft.com/blog)
- Community forums and YouTube demos

CRITICAL INSTRUCTIONS:
- Your ENTIRE response must be a single valid JSON object. Nothing before it, nothing after it.
- No intro text, no explanations, no markdown, no backticks, no commentary whatsoever.
- Start your response with {{ and end with }}
- Only include news and content published since {LOOKBACK} — do not go further back.

JSON structure (return exactly this shape):
{{
  "date": "YYYY-MM-DD",
  "lookback": "{LOOKBACK}",
  "summary": "2-3 sentence executive summary focused on the priority topics",
  "top_pick": {{
    "title": "headline of the single most important story — bias strongly toward priority topics",
    "detail": "2-3 sentences on why this is the top story, considering recency, practitioner impact, and breadth of coverage",
    "category": "category name",
    "source": "source name",
    "url": "https://... or empty string"
  }},
  "items": [
    {{
      "category": "Copilot Studio & Agents|Canvas & Model-driven Apps|Power Automate|Dataverse|Security & Governance|Power BI|Power Pages|Events|LinkedIn|General",
      "title": "short headline",
      "detail": "2-3 sentences describing the update and why it matters to practitioners",
      "source": "source name — for LinkedIn include the person or page name",
      "url": "https://... or empty string",
      "importance": "high|medium|low",
      "is_priority": true or false
    }}
  ],
  "learning": [
    {{
      "title": "title of the learning resource",
      "detail": "1-2 sentences on what you will learn and why it is relevant to this week's news",
      "format": "Blog|Video|Docs|Community|Course",
      "source": "source name",
      "url": "https://... or empty string",
      "related_to": "which news item or topic this ties back to"
    }}
  ]
}}

Return 8-14 news items total. Priority categories first, then standard. Include 3-5 learning resources directly tied to the week's top stories. Flag is_priority as true for priority category items."""


def fetch_digest() -> dict:
    logging.info("Fetching Power Platform digest from Claude (lookback: %s)...", LOOKBACK)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Fetch the Power Platform digest covering news since {LOOKBACK}."}],
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
    priority_cats = {
        "Copilot Studio & Agents", "Canvas & Model-driven Apps",
        "Power Automate", "Dataverse", "Security & Governance"
    }
    cat_colors = {
        "Copilot Studio & Agents": "#7F77DD",
        "Canvas & Model-driven Apps": "#378ADD",
        "Power Automate": "#1D9E75",
        "Dataverse": "#639922",
        "Security & Governance": "#E24B4A",
        "Power BI": "#EF9F27",
        "Power Pages": "#D85A30",
        "Events": "#D4537E",
        "LinkedIn": "#378ADD",
        "General": "#888780",
    }
    imp_colors = {"high": "#E24B4A", "medium": "#EF9F27", "low": "#888780"}
    format_icons = {"Blog": "✍️", "Video": "▶️", "Docs": "📄", "Community": "💬", "Course": "🎓"}

    date_str  = digest.get("date", datetime.today().strftime("%Y-%m-%d"))
    lookback  = digest.get("lookback", "the past few days")
    summary   = digest.get("summary", "")
    top_pick  = digest.get("top_pick", {})
    items     = digest.get("items", [])
    learning  = digest.get("learning", [])

    # Split items into priority and standard
    priority_items = [i for i in items if i.get("is_priority")]
    standard_items = [i for i in items if not i.get("is_priority")]

    def render_items(item_list):
        html = ""
        current_cat = None
        for item in item_list:
            cat = item.get("category", "General")
            color = cat_colors.get(cat, "#888780")
            imp_color = imp_colors.get(item.get("importance", "low"), "#888780")
            is_urgent = "ACTION REQUIRED" in item.get("title", "").upper()
            border = "#E24B4A" if is_urgent else "#e5e5e5"
            url_html = f'<a href="{item["url"]}" style="color:#378ADD;font-size:12px;text-decoration:none;">Read more ↗</a>' if item.get("url") else ""

            if cat != current_cat:
                current_cat = cat
                priority_badge = '<span style="background:#EEEDFE;color:#3C3489;font-size:10px;font-weight:600;padding:1px 6px;border-radius:99px;margin-left:6px;">priority</span>' if cat in priority_cats else ""
                html += f"""
                <div style="display:flex;align-items:center;gap:6px;margin:20px 0 8px;">
                  <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{color};"></span>
                  <span style="font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;letter-spacing:.06em;">{cat}</span>
                  {priority_badge}
                </div>"""

            html += f"""
            <div style="border:1px solid {border};border-radius:10px;padding:14px 16px;margin-bottom:8px;">
              <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
                <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:{imp_color};flex-shrink:0;"></span>
                <span style="font-size:11px;color:#888;">{item.get("source","")}</span>
              </div>
              <p style="margin:0 0 6px;font-size:14px;font-weight:600;color:{"#A32D2D" if is_urgent else "#111"};">{item.get("title","")}</p>
              <p style="margin:0 0 8px;font-size:13px;color:#555;line-height:1.6;">{item.get("detail","")}</p>
              {url_html}
            </div>"""
        return html

    # Learning section
    learning_html = ""
    for resource in learning:
        fmt = resource.get("format", "Blog")
        icon = format_icons.get(fmt, "📎")
        url_html = f'<a href="{resource["url"]}" style="color:#378ADD;font-size:12px;text-decoration:none;">Open resource ↗</a>' if resource.get("url") else ""
        learning_html += f"""
        <div style="border:1px solid #e5e5e5;border-radius:10px;padding:12px 16px;margin-bottom:8px;display:flex;gap:12px;align-items:flex-start;">
          <span style="font-size:18px;flex-shrink:0;">{icon}</span>
          <div>
            <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
              <span style="background:#E6F1FB;color:#0C447C;font-size:10px;font-weight:600;padding:1px 6px;border-radius:99px;">{fmt}</span>
              <span style="font-size:11px;color:#888;">{resource.get("source","")}</span>
            </div>
            <p style="margin:0 0 4px;font-size:13px;font-weight:600;color:#111;">{resource.get("title","")}</p>
            <p style="margin:0 0 6px;font-size:12px;color:#555;line-height:1.5;">{resource.get("detail","")}</p>
            <p style="margin:0 0 6px;font-size:11px;color:#888;">Related to: {resource.get("related_to","")}</p>
            {url_html}
          </div>
        </div>"""

    # Top pick
    top_pick_color = cat_colors.get(top_pick.get("category",""), "#7F77DD")
    top_pick_url = f'<a href="{top_pick["url"]}" style="color:{top_pick_color};font-size:12px;text-decoration:none;">Read more ↗</a>' if top_pick.get("url") else ""
    top_pick_html = f"""
    <div style="border:2px solid {top_pick_color};border-radius:10px;padding:16px;margin-bottom:20px;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <span style="font-size:13px;">⭐</span>
        <span style="background:{top_pick_color}22;color:{top_pick_color};font-size:11px;font-weight:600;padding:2px 8px;border-radius:99px;">{top_pick.get("category","")}</span>
        <span style="font-size:11px;color:#888;">{top_pick.get("source","")}</span>
      </div>
      <p style="margin:0 0 6px;font-size:15px;font-weight:600;color:#111;">{top_pick.get("title","")}</p>
      <p style="margin:0 0 10px;font-size:13px;color:#555;line-height:1.6;">{top_pick.get("detail","")}</p>
      {top_pick_url}
    </div>"""

    divider = '<div style="border-top:1px solid #e5e5e5;margin:20px 0 16px;"><p style="font-size:11px;color:#bbb;text-transform:uppercase;letter-spacing:.06em;margin:8px 0 0;">Other updates</p></div>' if standard_items else ""

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:600px;margin:0 auto;padding:24px 16px;background:#fff;color:#111;">

  <h2 style="font-size:20px;font-weight:600;margin:0 0 2px;">⚡ Power Platform digest</h2>
  <p style="font-size:13px;color:#888;margin:0 0 4px;">{date_str} · Covering news since {lookback}</p>
  <p style="font-size:11px;color:#bbb;margin:0 0 20px;">Priority focus: Copilot Studio · Agents · Canvas & Model-driven Apps · Power Automate · Dataverse · Security</p>

  <div style="background:#f7f7f7;border-radius:10px;padding:14px 16px;margin-bottom:20px;">
    <p style="font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;letter-spacing:.06em;margin:0 0 8px;">Summary</p>
    <p style="font-size:14px;line-height:1.7;margin:0;">{summary}</p>
  </div>

  <p style="font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;letter-spacing:.06em;margin:0 0 10px;">⭐ Top pick of the day</p>
  {top_pick_html}

  {render_items(priority_items)}
  {divider}
  {render_items(standard_items)}

  {"<p style='font-size:11px;font-weight:600;color:#aaa;text-transform:uppercase;letter-spacing:.06em;margin:24px 0 10px;'>📚 Learning this week</p>" + learning_html if learning_html else ""}

  <p style="font-size:11px;color:#bbb;margin-top:28px;text-align:center;border-top:1px solid #f0f0f0;padding-top:16px;">
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

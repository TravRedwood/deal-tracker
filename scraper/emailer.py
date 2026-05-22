import sqlite3, json, smtplib, secrets, logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from scraper.scraper import get_db, load_config

log = logging.getLogger(__name__)

def generate_magic_link(email, base_url):
    token = secrets.token_urlsafe(32)
    expiry = (datetime.utcnow() + timedelta(days=7)).isoformat()
    conn = get_db()
    conn.execute("UPDATE recipients SET magic_token=?, token_expiry=? WHERE email=?",
                 (token, expiry, email))
    conn.commit()
    conn.close()
    return f"{base_url}/auth?token={token}"

def get_digest_data(since_days=7):
    conn = get_db()
    now = datetime.utcnow()
    week_ago = (now - timedelta(days=since_days)).isoformat()
    new_listings = conn.execute("""
        SELECT * FROM listings WHERE first_seen >= ? AND status='active'
        ORDER BY match_score DESC
    """, (week_ago,)).fetchall()
    price_drops = conn.execute("""
        SELECT * FROM listings WHERE price_history != '[]' AND last_seen >= ?
        AND status='active'
    """, (week_ago,)).fetchall()
    watchlisted = conn.execute("""
        SELECT * FROM listings WHERE watchlisted=1 AND status='active'
        ORDER BY match_score DESC
    """).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM listings WHERE status='active'").fetchone()[0]
    conn.close()
    strong = [l for l in new_listings if l["match_score"] >= 75]
    flagged = [l for l in new_listings if l["flags"] and l["match_score"] < 75]
    return {
        "new_listings": new_listings,
        "strong_matches": strong,
        "flagged": flagged,
        "price_drops": [l for l in price_drops if l["id"] not in {x["id"] for x in new_listings}],
        "watchlisted": watchlisted,
        "total": total,
        "week": now.strftime("%B %d, %Y"),
    }

def fmt_price(val):
    if not val:
        return "N/A"
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    if val >= 1000:
        return f"${val//1000}K"
    return f"${val:,}"

def listing_html(l, badge_label, badge_color):
    flags = json.loads(l["flags"] or "[]")
    flag_html = ""
    if flags:
        flag_html = "".join(f'<div style="color:#991b1b;font-size:12px;margin-top:4px">⚠ {f}</div>' for f in flags)
    price_drop_html = ""
    ph = json.loads(l["price_history"] or "[]")
    if ph:
        old = ph[-1]["price"]
        diff = old - (l["asking_price"] or 0)
        if diff > 0:
            price_drop_html = f'<span style="color:#92400e;font-size:11px;margin-left:6px">was {fmt_price(old)} (↓{fmt_price(diff)})</span>'
    score_color = "#065f46" if l["match_score"] >= 80 else "#1e40af" if l["match_score"] >= 60 else "#92400e"
    return f"""
<div style="border:1px solid #e5e7eb;border-radius:8px;padding:14px 16px;margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px">
    <div style="flex:1">
      <p style="font-size:15px;font-weight:600;color:#111827;margin:0 0 2px">{l['title']}</p>
      <p style="font-size:12px;color:#6b7280;margin:0">{l['location'] or 'US'} · via {l['source']}</p>
    </div>
    <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0">
      <span style="background:{badge_color};color:white;font-size:10px;padding:2px 8px;border-radius:4px;font-weight:600">{badge_label}</span>
      <span style="background:#f0fdf4;color:{score_color};font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600">{l['match_score']}% match</span>
    </div>
  </div>
  <div style="display:flex;gap:14px;flex-wrap:wrap;margin:10px 0 6px">
    <span style="font-size:12px;color:#374151"><strong>{fmt_price(l['asking_price'])}</strong> asking{price_drop_html}</span>
    <span style="font-size:12px;color:#374151"><strong>{fmt_price(l['annual_revenue'])}</strong> revenue</span>
    <span style="font-size:12px;color:#374151"><strong>{l['profit_margin'] or 'N/A'}%</strong> margin</span>
    {'<span style="font-size:12px;color:#374151"><strong>SDE listed</strong></span>' if l['sde'] else ''}
    {'<span style="font-size:12px;color:#374151"><strong>Verified financials</strong></span>' if l['financials_verified'] else ''}
  </div>
  {f'<p style="font-size:12px;color:#6b7280;border-left:3px solid #d1d5db;padding-left:8px;margin:6px 0">{l["description"][:200]}...</p>' if l['description'] else ''}
  {flag_html}
  <a href="{l['url']}" style="font-size:12px;color:#1d4ed8;text-decoration:none;display:inline-block;margin-top:6px">View listing →</a>
</div>"""

def build_html_email(data, magic_link):
    strong_html = "".join(listing_html(l, "New", "#059669") for l in data["strong_matches"][:5]) or "<p style='color:#6b7280;font-size:14px'>No strong matches this week.</p>"
    flagged_html = "".join(listing_html(l, "Review", "#dc2626") for l in data["flagged"][:3]) if data["flagged"] else ""
    drops_html = "".join(listing_html(l, "Price drop", "#d97706") for l in data["price_drops"][:3]) if data["price_drops"] else ""
    watch_html = "".join(f"""
<div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid #f3f4f6;font-size:13px">
  <span style="color:#111827;font-weight:500">{l['title']}</span>
  <span style="color:#6b7280">{('No change' if not json.loads(l['price_history'] or '[]') else 'Price change')} · {l['days_on_market'] or '?'} days on market</span>
</div>""" for l in data["watchlisted"]) or "<p style='color:#6b7280;font-size:13px'>Nothing on your watchlist yet.</p>"

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f9fafb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif">
<div style="max-width:600px;margin:0 auto;padding:24px 16px">
  <div style="background:#1c1c1a;border-radius:10px 10px 0 0;padding:20px 24px">
    <p style="font-size:17px;font-weight:600;color:#f9fafb;margin:0 0 3px">Your weekly deal digest</p>
    <p style="font-size:12px;color:#9ca3af;margin:0">Week of {data['week']} · {len(data['new_listings'])} new listings · {len(data['strong_matches'])} strong matches</p>
  </div>
  <div style="background:#ffffff;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 10px 10px;padding:20px 24px">
    <div style="display:flex;gap:16px;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid #f3f4f6">
      <div style="text-align:center;flex:1"><p style="font-size:24px;font-weight:600;color:#111827;margin:0">{len(data['new_listings'])}</p><p style="font-size:11px;color:#6b7280;margin:3px 0 0">New listings</p></div>
      <div style="text-align:center;flex:1"><p style="font-size:24px;font-weight:600;color:#111827;margin:0">{len(data['strong_matches'])}</p><p style="font-size:11px;color:#6b7280;margin:3px 0 0">Strong matches</p></div>
      <div style="text-align:center;flex:1"><p style="font-size:24px;font-weight:600;color:#111827;margin:0">{len(data['price_drops'])}</p><p style="font-size:11px;color:#6b7280;margin:3px 0 0">Price drops</p></div>
      <div style="text-align:center;flex:1"><p style="font-size:24px;font-weight:600;color:#111827;margin:0">{len(data['watchlisted'])}</p><p style="font-size:11px;color:#6b7280;margin:3px 0 0">Watchlist updates</p></div>
    </div>
    <p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin:0 0 10px">Strong matches this week</p>
    {strong_html}
    {f'<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin:16px 0 10px">Price drops</p>{drops_html}' if drops_html else ''}
    {f'<p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin:16px 0 10px">Flagged for review</p>{flagged_html}' if flagged_html else ''}
    <p style="font-size:11px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.06em;margin:16px 0 10px">Your watchlist</p>
    {watch_html}
    <div style="margin-top:20px;padding-top:16px;border-top:1px solid #f3f4f6;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:11px;color:#9ca3af">Sent weekly · {data['total']} total listings tracked</span>
      <a href="{magic_link}" style="font-size:12px;color:#1d4ed8;text-decoration:none">Open dashboard →</a>
    </div>
  </div>
</div>
</body></html>"""

def send_digest():
    config = load_config()
    data = get_digest_data()
    conn = get_db()
    recipients = conn.execute("SELECT * FROM recipients").fetchall()
    conn.close()
    if not recipients:
        log.warning("No recipients found in database")
        return
    smtp_host = "smtp.gmail.com"
    smtp_port = 587
    import os
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    base_url = os.environ.get("BASE_URL", "http://localhost:5000")
    if not smtp_user or not smtp_pass:
        log.error("SMTP credentials not set. Set SMTP_USER and SMTP_PASS environment variables.")
        return
    for recipient in recipients:
        try:
            magic_link = generate_magic_link(recipient["email"], base_url)
            html = build_html_email(data, magic_link)
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"Your deal digest — {len(data['strong_matches'])} strong matches this week"
            msg["From"] = smtp_user
            msg["To"] = recipient["email"]
            msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, recipient["email"], msg.as_string())
            db = get_db()
            db.execute("""INSERT INTO digest_log (sent_at,recipient_email,listings_count,new_count)
                VALUES (?,?,?,?)""", (datetime.utcnow().isoformat(), recipient["email"],
                                     data["total"], len(data["new_listings"])))
            db.commit()
            db.close()
            log.info(f"Digest sent to {recipient['email']}")
        except Exception as e:
            log.error(f"Failed to send to {recipient['email']}: {e}")

if __name__ == "__main__":
    send_digest()

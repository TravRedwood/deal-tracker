# Deal Tracker — Setup Guide

Your business acquisition monitoring tool. Scrapes BizBuySell, BizQuest, Acquire.com, Flippa, and Sunbelt, scores listings against your criteria, and sends a weekly digest to all recipients.

---

## What you need before starting

- A computer with Python 3.10+ installed (Mac, Windows, or Linux)
- A Gmail account to send digest emails (or any SMTP email)
- A free Railway account to host it: https://railway.app

---

## Step 1 — First-time setup (one time only)

Open Terminal (Mac) or Command Prompt (Windows) and run:

```bash
cd deal-tracker
pip install -r requirements.txt
```

---

## Step 2 — Set your email credentials

Create a file called `.env` in the deal-tracker folder with these lines:

```
SMTP_USER=yourgmail@gmail.com
SMTP_PASS=your-gmail-app-password
DASHBOARD_PASSWORD=choose-a-password
SECRET_KEY=any-random-string-here
BASE_URL=https://your-app.railway.app
```

**Gmail App Password setup:**
1. Go to myaccount.google.com → Security
2. Enable 2-Step Verification
3. Search for "App passwords" → create one for "Mail"
4. Paste that 16-character password as SMTP_PASS

---

## Step 3 — Update your email addresses

Open `config.json` and replace the placeholder emails:

```json
"recipients": [
  {"email": "you@youremail.com", "name": "Your Name", "role": "owner"},
  {"email": "partner@email.com", "name": "Partner Name", "role": "full"}
]
```

---

## Step 4 — Run it locally (to test)

```bash
python main.py
```

Open http://localhost:5000 in your browser.
Default password: `dealtracker2024` (change this in .env)

Click "Run scraper now" to pull your first batch of listings.
Click "Send test digest" in Settings to verify emails are working.

---

## Step 5 — Deploy to Railway (so it runs 24/7)

1. Go to https://railway.app and sign up (free)
2. Install the Railway CLI:
   ```bash
   npm install -g @railway/cli
   ```
3. From your deal-tracker folder:
   ```bash
   railway login
   railway init
   railway up
   ```
4. In the Railway dashboard, go to Variables and add all your .env values
5. Railway gives you a public URL — set that as BASE_URL in your variables
6. Share that URL + your DASHBOARD_PASSWORD with your partner

That's it. The scraper runs every 6 hours automatically. Digest goes out every Monday at 8am.

---

## Day-to-day usage

**Dashboard** — view listings, filter by type, watchlist deals, add notes
**Settings page** — adjust price filters, toggle sources, add/remove recipients, change keywords
**Weekly email** — arrives Monday morning with new matches, price drops, watchlist updates. One-click login via magic link.

---

## Adding new business types to track

In Settings → Keywords, type your new keyword under any existing category, or ask me to add a new category entirely.

---

## Facebook Marketplace (manual)

Facebook doesn't allow scraping. Use these saved search URLs to check manually:
- https://www.facebook.com/marketplace/category/businesses-for-sale
- Filter by price range and search your keywords

---

## Troubleshooting

**"No listings found"** — Sites may have changed their HTML. Run the scraper and check the terminal for warnings. 

**Emails not sending** — Double-check your Gmail App Password. Regular Gmail passwords don't work — it must be an App Password.

**Railway deployment fails** — Make sure all environment variables are set in the Railway dashboard under Variables.

---

## File structure

```
deal-tracker/
├── main.py              # Start the app
├── app.py               # Dashboard web server
├── scheduler.py         # Runs scraper + digest on schedule
├── config.json          # Your filters, keywords, sources
├── requirements.txt     # Python dependencies
├── railway.toml         # Deployment config
├── scraper/
│   ├── scraper.py       # Crawls all sources
│   └── emailer.py       # Builds and sends digest emails
├── dashboard/
│   └── templates/       # Dashboard HTML pages
└── data/
    └── listings.db      # SQLite database (auto-created)
```

# Deal Tracker

A business acquisition monitoring tool designed to automate the discovery and evaluation of small business listings across major marketplaces. Built as part of an active personal search to acquire a small business as a long-term investment strategy.

> **Note:** This project was built with AI assistance (Claude by Anthropic). My contributions focused on product decision-making, search criteria design, technical setup, debugging, and deployment direction.

---

## Background & Motivation

Searching for businesses to acquire is a manual, fragmented process. Listings are spread across multiple platforms, new deals appear daily, and there is no unified way to filter, score, and track opportunities against a consistent set of personal investment criteria.

The goal was to define those criteria clearly, then build a tool to automate discovery and surface the right deals — rather than spending hours manually browsing marketplaces.

---

## My Role

| Area | Contribution |
|---|---|
| Product vision | Defined the problem, the user need, and what the tool needed to do |
| Search criteria | Designed all filters — price range, revenue floor, margin threshold, business types, franchise rules, risk flags |
| Architecture decisions | Chose the tech stack, hosting approach, email strategy, and auth model |
| Setup & debugging | Installed dependencies, resolved environment errors, managed virtual environments, configured Gmail and .env |
| Deployment direction | Directed Railway deployment strategy and GitHub portfolio setup |
| Pivots | Identified when approaches weren't working (bot blocking) and directed the pivot to alternative solutions |

---

## What It Does

- Monitors business-for-sale marketplaces for listings matching custom investment criteria
- Scores each listing against financial filters — asking price, annual revenue, profit margin, SDE
- Flags risk signals — key-person dependency, days on market, margin below threshold
- Sends a weekly HTML email digest to all recipients with new matches, price drops, and watchlist updates
- Provides a shared web dashboard for reviewing, watchlisting, and annotating deals
- Supports magic-link login from digest emails — no password required from email

---

## Target Marketplaces

The tool was designed to monitor:

- **BizBuySell** — largest US business-for-sale marketplace
- **BizQuest** — broad SMB listing network
- **Acquire.com** — focused on digital and tech-enabled businesses
- **Flippa** — online businesses, SaaS, and content sites
- **Sunbelt Business Brokers** — broker-listed deals, typically higher quality
- **Facebook Marketplace** — active for sub-$300K deals, salons and QSR

---

## The Core Challenge — Bot Protection

Every marketplace on the target list employs aggressive bot detection, primarily through Cloudflare. Three approaches were attempted:

**Attempt 1 — HTTP requests with BeautifulSoup**
Standard requests with browser-like headers. All sites returned `403 Forbidden` or `Access Denied`. Sites detect the absence of a real browser environment at the request level.

**Attempt 2 — Headless browser with Playwright**
Launched a real Chromium browser invisibly to render JavaScript and mimic human behavior. BizBuySell returned `Access Denied` at the page level. Zero listing cards returned across all keyword searches despite pages partially loading.

**Attempt 3 — RSS feeds and public APIs**
Attempted RSS feeds and JSON endpoints directly. BizBuySell RSS returned `403 Forbidden`. All marketplace APIs returned `Host not in allowlist` — Cloudflare blocking all non-allowlisted traffic at the network level.

**Conclusion:** These platforms treat listing data as a core business asset and have invested heavily in preventing aggregation. This is a known industry-wide limitation. The decision was made to pivot rather than continue fighting bot detection infrastructure.

**Planned resolution:** Integrate Gmail API to parse native listing alert emails from saved marketplace searches — bypassing bot protection by using the platforms' own alert systems, which is how professional acquisition searchers operate anyway.

---

## Investment Criteria

All filters are configurable from the dashboard settings page:

- **Price range:** $100K – $500K asking price
- **Min annual revenue:** $150K+
- **Min profit margin:** 15%+
- **Franchise filter:** Included only if total investment under $200K
- **Days on market flag:** 180+ days flagged as potential negotiating opportunity
- **Key-person risk:** Flagged when owner appears to be sole operator

**Business types monitored:**
Home services · Staffing agencies · Laundromats · Nail salons · Quick service restaurants · Route-based distribution

---

## Architecture

```
deal-tracker/
├── main.py                  # Entry point — starts app and scheduler
├── app.py                   # Flask web server — dashboard and API routes
├── scheduler.py             # APScheduler — scraper every 6hrs, digest weekly
├── config.example.json      # Template for filters, keywords, sources, recipients
├── requirements.txt         # Python dependencies
├── railway.toml             # Railway deployment config
├── scraper/
│   ├── scraper.py           # Core scraping logic and database operations
│   └── emailer.py           # HTML digest builder and SMTP sender
└── dashboard/
    └── templates/
        ├── dashboard.html   # Main listings view
        ├── settings.html    # Filter, keyword, and recipient management
        └── login.html       # Password and magic-link auth
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| Web framework | Flask | Lightweight, easy to self-host or deploy |
| Database | SQLite | Zero-config, portable, right-sized for single-user scale |
| Browser automation | Playwright | Best-in-class headless browser, handles JS rendering |
| Scheduling | APScheduler | In-process scheduler, no separate worker needed |
| Email | SMTP via Gmail | Simple, no third-party dependency |
| Deployment | Railway | One-command deploy, free tier, persistent storage |
| Auth | Magic links + session | Frictionless for shared use across devices |

---

## Setup

See [SETUP.md](SETUP.md) for full installation and deployment instructions.

**Quick start:**
```bash
git clone https://github.com/YOURUSERNAME/deal-tracker.git
cd deal-tracker
cp config.example.json config.json
pip install -r requirements.txt
python main.py
```

---

## Current Status

The dashboard, scoring engine, email digest, scheduling, and authentication are fully operational. The scraping layer is built but blocked by marketplace bot protection at all major sources.

**Next steps:**
- Gmail API integration to parse native marketplace alert emails
- Paid scraping API layer (ScraperAPI or Bright Data) for direct access
- Railway deployment for 24/7 monitoring
- SDE multiple benchmarking by business type in the scoring model

---

## Key Takeaways

This project involved real product decisions under ambiguity — defining search criteria before the tool existed, debugging a live environment across multiple failure modes, and pivoting strategy when the technical approach hit a wall.

The progression from HTTP requests → headless browsers → RSS/API attempts mirrors how engineering teams triage access problems in practice. Recognizing when to stop and redesign the approach — rather than continuing to push against Cloudflare — was the most important decision made in this project.

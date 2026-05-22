import json, sqlite3, hashlib, time, random, logging, re
from datetime import datetime
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

def load_config():
    with open("config.json") as f:
        return json.load(f)

def get_db():
    conn = sqlite3.connect("data/listings.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            title TEXT,
            source TEXT,
            url TEXT,
            location TEXT,
            business_type TEXT,
            asking_price INTEGER,
            annual_revenue INTEGER,
            profit_margin REAL,
            sde INTEGER,
            years_in_business INTEGER,
            days_on_market INTEGER,
            is_franchise INTEGER DEFAULT 0,
            franchise_investment INTEGER,
            reason_for_sale TEXT,
            financials_verified INTEGER DEFAULT 0,
            key_person_risk INTEGER DEFAULT 0,
            description TEXT,
            match_score INTEGER,
            flags TEXT,
            first_seen TEXT,
            last_seen TEXT,
            price_history TEXT,
            watchlisted INTEGER DEFAULT 0,
            notes TEXT,
            status TEXT DEFAULT 'active'
        );
        CREATE TABLE IF NOT EXISTS recipients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE,
            name TEXT,
            role TEXT DEFAULT 'full',
            magic_token TEXT,
            token_expiry TEXT,
            added_at TEXT
        );
        CREATE TABLE IF NOT EXISTS digest_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at TEXT,
            recipient_email TEXT,
            listings_count INTEGER,
            new_count INTEGER
        );
    """)
    conn.commit()
    conn.close()
    log.info("Database initialized")

def make_id(source, url):
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()

def parse_price(text):
    if not text:
        return 0
    text = str(text).replace(",", "").replace("$", "").strip()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Mm]", text)
    if m:
        return int(float(m.group(1)) * 1_000_000)
    m = re.search(r"(\d+(?:\.\d+)?)\s*[Kk]", text)
    if m:
        return int(float(m.group(1)) * 1000)
    m = re.search(r"(\d{4,})", text.replace(",", ""))
    if m:
        return int(m.group(1))
    return 0

def calc_margin(revenue, price):
    if revenue and price and revenue > 0:
        estimated_profit = revenue * 0.20
        return round((estimated_profit / revenue) * 100, 1)
    return 0

def match_keyword_category(text, keywords):
    text_lower = text.lower()
    for category, kws in keywords.items():
        for kw in kws:
            if kw.lower() in text_lower:
                return category
    return None

def score_listing(listing, config):
    f = config["filters"]
    score = 0
    flags = []

    price = listing.get("asking_price", 0) or 0
    revenue = listing.get("annual_revenue", 0) or 0
    margin = listing.get("profit_margin", 0) or 0
    dom = listing.get("days_on_market", 0) or 0
    verified = listing.get("financials_verified", False)
    key_person = listing.get("key_person_risk", False)
    is_franchise = listing.get("is_franchise", False)
    franchise_inv = listing.get("franchise_investment", 0) or 0

    if price > 0 and f["price_min"] <= price <= f["price_max"]:
        score += 25
    if revenue >= f["revenue_min"]:
        score += 20
    if margin >= f["margin_min"]:
        score += 20
    elif margin > 0:
        score += 10
    if verified:
        score += 15
    if revenue > 0 and price > 0 and (price / revenue) <= f["price_to_revenue_flag"]:
        score += 10
    if listing.get("sde"):
        score += 5
    if listing.get("reason_for_sale"):
        score += 5

    if dom >= f["days_on_market_flag"]:
        flags.append(f"{dom} days on market — potential negotiating room")
    if key_person:
        flags.append("Key-person risk — owner may be central to operations")
    if 0 < margin < f["margin_min"]:
        flags.append(f"Margin ({margin}%) below your {f['margin_min']}% threshold")
    if is_franchise and franchise_inv > f["franchise_max_investment"]:
        flags.append(f"Franchise investment (${franchise_inv:,}) exceeds your ${f['franchise_max_investment']:,} limit")
        score = max(0, score - 30)

    return min(score, 99), flags

def scrape_bizbuysell(page, keywords, config):
    listings = []
    f = config["filters"]
    log.info("Scraping BizBuySell...")
    for category, kws in keywords.items():
        for kw in kws[:2]:
            try:
                url = f"https://www.bizbuysell.com/businesses-for-sale/?q={kw.replace(' ', '+')}&priceMin={f['price_min']}&priceMax={f['price_max']}"
                log.info(f"  BizBuySell: {kw}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                cards = page.query_selector_all(".result-item, .listing-card, [data-id]")
                if not cards:
                    cards = page.query_selector_all("ul.results li, .businesses li")
                log.info(f"  Found {len(cards)} cards for '{kw}'")
                for card in cards[:8]:
                    try:
                        title_el = card.query_selector("a.title, h2 a, h3 a, .listing-title a, a[href*='/business-for-sale/']")
                        if not title_el:
                            continue
                        title = title_el.inner_text().strip()
                        href = title_el.get_attribute("href") or ""
                        if not href.startswith("http"):
                            href = "https://www.bizbuysell.com" + href
                        lid = make_id("bizbuysell", href)
                        full_text = card.inner_text()
                        price = 0
                        price_el = card.query_selector(".price, .asking-price, [class*='price']")
                        if price_el:
                            price = parse_price(price_el.inner_text())
                        if not price:
                            price = parse_price(full_text)
                        revenue = 0
                        rev_patterns = ["revenue", "gross", "sales"]
                        for pat in rev_patterns:
                            rev_match = re.search(rf"{pat}[:\s]*\$?([\d,]+\.?\d*[KkMm]?)", full_text, re.I)
                            if rev_match:
                                revenue = parse_price(rev_match.group(1))
                                break
                        loc_el = card.query_selector(".location, .city-state, [class*='location']")
                        location = loc_el.inner_text().strip() if loc_el else "US"
                        desc_el = card.query_selector(".description, .teaser, p")
                        desc = desc_el.inner_text().strip()[:300] if desc_el else ""
                        if not title or len(title) < 3:
                            continue
                        listings.append({
                            "id": lid, "title": title, "source": "BizBuySell",
                            "url": href, "location": location,
                            "business_type": category, "asking_price": price,
                            "annual_revenue": revenue,
                            "profit_margin": calc_margin(revenue, price),
                            "description": desc, "sde": None,
                            "years_in_business": None, "days_on_market": None,
                            "is_franchise": False, "financials_verified": False,
                            "key_person_risk": False, "reason_for_sale": None,
                            "franchise_investment": None,
                        })
                    except Exception as e:
                        log.debug(f"Card parse error: {e}")
                time.sleep(random.uniform(2, 4))
            except PlaywrightTimeout:
                log.warning(f"BizBuySell timeout for '{kw}'")
            except Exception as e:
                log.warning(f"BizBuySell error for '{kw}': {e}")
    log.info(f"BizBuySell: {len(listings)} listings found")
    return listings

def scrape_bizquest(page, keywords, config):
    listings = []
    f = config["filters"]
    log.info("Scraping BizQuest...")
    for category, kws in keywords.items():
        for kw in kws[:2]:
            try:
                url = f"https://www.bizquest.com/business-for-sale/?Search={kw.replace(' ', '+')}&PriceMin={f['price_min']}&PriceMax={f['price_max']}"
                log.info(f"  BizQuest: {kw}")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                cards = page.query_selector_all(".listing, .srp-listing, .business-listing, .result")
                if not cards:
                    cards = page.query_selector_all("article, .card")
                log.info(f"  Found {len(cards)} cards for '{kw}'")
                for card in cards[:8]:
                    try:
                        title_el = card.query_selector("a.listing-title, h2 a, h3 a, .title a, a[href*='/business']")
                        if not title_el:
                            continue
                        title = title_el.inner_text().strip()
                        href = title_el.get_attribute("href") or ""
                        if not href.startswith("http"):
                            href = "https://www.bizquest.com" + href
                        lid = make_id("bizquest", href)
                        full_text = card.inner_text()
                        price = parse_price(full_text)
                        loc_el = card.query_selector(".location, .city, [class*='location']")
                        location = loc_el.inner_text().strip() if loc_el else "US"
                        desc_el = card.query_selector(".description, p")
                        desc = desc_el.inner_text().strip()[:300] if desc_el else ""
                        if not title or len(title) < 3:
                            continue
                        listings.append({
                            "id": lid, "title": title, "source": "BizQuest",
                            "url": href, "location": location,
                            "business_type": category, "asking_price": price,
                            "annual_revenue": 0,
                            "profit_margin": 0,
                            "description": desc, "sde": None,
                            "years_in_business": None, "days_on_market": None,
                            "is_franchise": False, "financials_verified": False,
                            "key_person_risk": False, "reason_for_sale": None,
                            "franchise_investment": None,
                        })
                    except Exception as e:
                        log.debug(f"Card parse error: {e}")
                time.sleep(random.uniform(2, 4))
            except PlaywrightTimeout:
                log.warning(f"BizQuest timeout for '{kw}'")
            except Exception as e:
                log.warning(f"BizQuest error for '{kw}': {e}")
    log.info(f"BizQuest: {len(listings)} listings found")
    return listings

def scrape_acquire(keywords, config):
    import requests
    listings = []
    f = config["filters"]
    log.info("Scraping Acquire.com...")
    try:
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
        url = "https://acquire.com/api/listings?status=active&sort=newest&limit=50"
        r = requests.get(url, headers=headers, timeout=15)
        if r.ok:
            data = r.json()
            items = data.get("listings", data.get("data", []))
            for item in items:
                price = item.get("asking_price", 0) or 0
                revenue = item.get("annual_revenue", item.get("ttm_revenue", 0)) or 0
                if not (f["price_min"] <= price <= f["price_max"]):
                    continue
                title = item.get("name", item.get("title", "Unnamed"))
                slug = item.get("slug", item.get("id", ""))
                href = f"https://acquire.com/listings/{slug}"
                lid = make_id("acquire", href)
                desc = item.get("description", "")[:300]
                btype = match_keyword_category(title + " " + desc, keywords)
                listings.append({
                    "id": lid, "title": title, "source": "Acquire.com",
                    "url": href, "location": item.get("location", "Remote/US"),
                    "business_type": btype or "Other",
                    "asking_price": price, "annual_revenue": revenue,
                    "profit_margin": calc_margin(revenue, price),
                    "description": desc,
                    "sde": item.get("sde"),
                    "years_in_business": item.get("years_in_operation"),
                    "days_on_market": None,
                    "is_franchise": False,
                    "financials_verified": item.get("verified", False),
                    "key_person_risk": False,
                    "reason_for_sale": None,
                    "franchise_investment": None,
                })
        log.info(f"Acquire.com: {len(listings)} listings found")
    except Exception as e:
        log.warning(f"Acquire.com error: {e}")
    return listings

def save_listings(listings, config):
    conn = get_db()
    now = datetime.utcnow().isoformat()
    new_count = 0
    for l in listings:
        score, flags = score_listing(l, config)
        existing = conn.execute(
            "SELECT id, asking_price, price_history FROM listings WHERE id=?",
            (l["id"],)
        ).fetchone()
        if existing:
            price_history = json.loads(existing["price_history"] or "[]")
            if existing["asking_price"] and l["asking_price"] and existing["asking_price"] != l["asking_price"]:
                price_history.append({"price": existing["asking_price"], "date": now})
            conn.execute("""
                UPDATE listings SET last_seen=?, asking_price=?, annual_revenue=?,
                profit_margin=?, match_score=?, flags=?, price_history=?, status='active'
                WHERE id=?
            """, (now, l["asking_price"], l["annual_revenue"], l["profit_margin"],
                  score, json.dumps(flags), json.dumps(price_history), l["id"]))
        else:
            new_count += 1
            conn.execute("""
                INSERT INTO listings (id,title,source,url,location,business_type,
                asking_price,annual_revenue,profit_margin,sde,years_in_business,
                days_on_market,is_franchise,franchise_investment,reason_for_sale,
                financials_verified,key_person_risk,description,match_score,flags,
                first_seen,last_seen,price_history,watchlisted,notes,status)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,NULL,'active')
            """, (
                l["id"], l["title"], l["source"], l["url"], l["location"],
                l["business_type"], l["asking_price"], l["annual_revenue"],
                l["profit_margin"], l.get("sde"), l.get("years_in_business"),
                l.get("days_on_market"), int(l.get("is_franchise", False)),
                l.get("franchise_investment"), l.get("reason_for_sale"),
                int(l.get("financials_verified", False)),
                int(l.get("key_person_risk", False)),
                l.get("description", ""), score, json.dumps(flags),
                now, now, "[]"
            ))
    conn.commit()
    conn.close()
    log.info(f"Saved {len(listings)} listings ({new_count} new)")
    return new_count

def run_scraper():
    config = load_config()
    init_db()
    keywords = config["keywords"]
    sources = config["sources"]
    all_listings = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        page.set_default_timeout(30000)

        if sources.get("bizbuysell"):
            all_listings += scrape_bizbuysell(page, keywords, config)
        if sources.get("bizquest"):
            all_listings += scrape_bizquest(page, keywords, config)

        browser.close()

    if sources.get("acquire"):
        all_listings += scrape_acquire(keywords, config)

    seen_ids = set()
    deduped = []
    for l in all_listings:
        if l["id"] not in seen_ids:
            seen_ids.add(l["id"])
            deduped.append(l)

    new_count = save_listings(deduped, config)
    log.info(f"Scrape complete: {len(deduped)} total listings, {new_count} new")
    return len(deduped), new_count

if __name__ == "__main__":
    run_scraper()
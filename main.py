import os, logging
from scraper.scraper import init_db, load_config, get_db
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

if __name__ == "__main__":
    print("\n=== Deal Tracker starting ===\n")
    init_db()
    config = load_config()
    conn = get_db()
    for r in config.get("recipients", []):
        try:
            conn.execute(
                "INSERT OR IGNORE INTO recipients (email,name,role,added_at) VALUES (?,?,?,?)",
                (r["email"], r["name"], r.get("role", "full"), datetime.utcnow().isoformat())
            )
        except Exception:
            pass
    conn.commit()
    conn.close()
    from scheduler import start_scheduler
    start_scheduler()
    from app import app
    port = int(os.environ.get("PORT", 5000))
    print(f"Dashboard running at http://localhost:{port}")
    print(f"Default password: {os.environ.get('DASHBOARD_PASSWORD', 'dealtracker2024')}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

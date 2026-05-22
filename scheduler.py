from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import json, logging, atexit

log = logging.getLogger(__name__)

def load_config():
    with open("config.json") as f:
        return json.load(f)

def run_scrape_job():
    from scraper.scraper import run_scraper
    log.info("Scheduled scrape starting...")
    try:
        total, new = run_scraper()
        log.info(f"Scheduled scrape done: {total} listings, {new} new")
    except Exception as e:
        log.error(f"Scheduled scrape failed: {e}")

def run_digest_job():
    from scraper.emailer import send_digest
    log.info("Sending weekly digest...")
    try:
        send_digest()
        log.info("Weekly digest sent")
    except Exception as e:
        log.error(f"Digest failed: {e}")

def start_scheduler():
    config = load_config()
    digest = config.get("digest", {})
    day = digest.get("day", "monday")
    time_str = digest.get("time", "08:00")
    hour, minute = time_str.split(":")

    scheduler = BackgroundScheduler()
    scheduler.add_job(run_scrape_job, CronTrigger(hour="*/6"), id="scraper",
                      replace_existing=True)
    scheduler.add_job(run_digest_job, CronTrigger(day_of_week=day[:3], hour=int(hour), minute=int(minute)),
                      id="digest", replace_existing=True)
    scheduler.start()
    log.info(f"Scheduler started — scraping every 6 hours, digest every {day} at {time_str}")
    atexit.register(lambda: scheduler.shutdown())
    return scheduler

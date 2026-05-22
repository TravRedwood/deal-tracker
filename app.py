from flask import Flask, render_template, request, jsonify, redirect, session, url_for, abort
import sqlite3, json, os, secrets
from datetime import datetime, timedelta
from scraper.scraper import get_db, load_config, run_scraper, init_db
from scraper.emailer import send_digest, generate_magic_link

app = Flask(__name__, template_folder='dashboard/templates')
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_hex(32))

def require_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

@app.route("/auth")
def auth_magic():
    token = request.args.get("token")
    if not token:
        abort(400)
    conn = get_db()
    user = conn.execute("SELECT * FROM recipients WHERE magic_token=?", (token,)).fetchone()
    conn.close()
    if not user:
        return "Invalid or expired link.", 403
    expiry = datetime.fromisoformat(user["token_expiry"])
    if datetime.utcnow() > expiry:
        return "This link has expired. Please request a new digest email.", 403
    session["authenticated"] = True
    session["user_email"] = user["email"]
    session["user_name"] = user["name"]
    return redirect(url_for("dashboard"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        if password == os.environ.get("DASHBOARD_PASSWORD", "dealtracker2024"):
            session["authenticated"] = True
            session["user_email"] = "admin"
            session["user_name"] = "Admin"
            return redirect(url_for("dashboard"))
        error = "Incorrect password."
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@require_auth
def dashboard():
    conn = get_db()
    config = load_config()
    total = conn.execute("SELECT COUNT(*) FROM listings WHERE status='active'").fetchone()[0]
    new_today = conn.execute("SELECT COUNT(*) FROM listings WHERE date(first_seen)=date('now')").fetchone()[0]
    watchlisted = conn.execute("SELECT COUNT(*) FROM listings WHERE watchlisted=1").fetchone()[0]
    strong = conn.execute("SELECT COUNT(*) FROM listings WHERE match_score >= 75 AND status='active'").fetchone()[0]
    conn.close()
    return render_template("dashboard.html",
        total=total, new_today=new_today, watchlisted=watchlisted,
        strong=strong, user_name=session.get("user_name", ""),
        config=config)

@app.route("/api/listings")
@require_auth
def api_listings():
    conn = get_db()
    config = load_config()
    btype = request.args.get("type", "all")
    sort = request.args.get("sort", "score")
    tab = request.args.get("tab", "all")
    query = "SELECT * FROM listings WHERE status='active'"
    params = []
    if btype != "all":
        query += " AND business_type=?"
        params.append(btype)
    if tab == "watchlist":
        query += " AND watchlisted=1"
    elif tab == "strong":
        query += " AND match_score >= 75"
    elif tab == "flagged":
        query += " AND json_array_length(flags) > 0"
    sort_map = {"score": "match_score DESC", "newest": "first_seen DESC",
                "price_asc": "asking_price ASC", "price_desc": "asking_price DESC",
                "revenue": "annual_revenue DESC"}
    query += f" ORDER BY {sort_map.get(sort, 'match_score DESC')} LIMIT 50"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    listings = []
    for r in rows:
        d = dict(r)
        d["flags"] = json.loads(d["flags"] or "[]")
        d["price_history"] = json.loads(d["price_history"] or "[]")
        listings.append(d)
    return jsonify(listings)

@app.route("/api/listings/<lid>/watch", methods=["POST"])
@require_auth
def toggle_watch(lid):
    conn = get_db()
    current = conn.execute("SELECT watchlisted FROM listings WHERE id=?", (lid,)).fetchone()
    if not current:
        conn.close()
        return jsonify({"error": "Not found"}), 404
    new_val = 0 if current["watchlisted"] else 1
    conn.execute("UPDATE listings SET watchlisted=? WHERE id=?", (new_val, lid))
    conn.commit()
    conn.close()
    return jsonify({"watchlisted": bool(new_val)})

@app.route("/api/listings/<lid>/notes", methods=["POST"])
@require_auth
def save_notes(lid):
    notes = request.json.get("notes", "")
    conn = get_db()
    conn.execute("UPDATE listings SET notes=? WHERE id=?", (notes, lid))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET", "POST"])
@require_auth
def api_config():
    if request.method == "POST":
        new_config = request.json
        with open("config.json", "w") as f:
            json.dump(new_config, f, indent=2)
        return jsonify({"ok": True})
    return jsonify(load_config())

@app.route("/api/recipients", methods=["GET", "POST", "DELETE"])
@require_auth
def api_recipients():
    conn = get_db()
    if request.method == "GET":
        rows = conn.execute("SELECT id,email,name,role,added_at FROM recipients").fetchall()
        conn.close()
        return jsonify([dict(r) for r in rows])
    if request.method == "POST":
        data = request.json
        email = data.get("email", "").strip().lower()
        name = data.get("name", "").strip()
        role = data.get("role", "full")
        if not email:
            conn.close()
            return jsonify({"error": "Email required"}), 400
        try:
            conn.execute("INSERT INTO recipients (email,name,role,added_at) VALUES (?,?,?,?)",
                        (email, name, role, datetime.utcnow().isoformat()))
            conn.commit()
        except sqlite3.IntegrityError:
            conn.close()
            return jsonify({"error": "Email already exists"}), 409
        conn.close()
        return jsonify({"ok": True})
    if request.method == "DELETE":
        email = request.json.get("email")
        conn.execute("DELETE FROM recipients WHERE email=?", (email,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

@app.route("/api/scrape", methods=["POST"])
@require_auth
def trigger_scrape():
    try:
        total, new = run_scraper()
        return jsonify({"ok": True, "total": total, "new": new})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/send-digest", methods=["POST"])
@require_auth
def trigger_digest():
    try:
        send_digest()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/settings")
@require_auth
def settings():
    config = load_config()
    conn = get_db()
    recipients = conn.execute("SELECT id,email,name,role,added_at FROM recipients").fetchall()
    conn.close()
    return render_template("settings.html",
        config=config, recipients=[dict(r) for r in recipients],
        user_name=session.get("user_name", ""))

if __name__ == "__main__":
    init_db()
    from scraper.scraper import load_config
    config = load_config()
    conn = get_db()
    for r in config.get("recipients", []):
        try:
            conn.execute("INSERT OR IGNORE INTO recipients (email,name,role,added_at) VALUES (?,?,?,?)",
                        (r["email"], r["name"], r.get("role","full"), datetime.utcnow().isoformat()))
        except Exception:
            pass
    conn.commit()
    conn.close()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

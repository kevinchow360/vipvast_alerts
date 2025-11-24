from flask import Flask, render_template, jsonify
import feedparser
from datetime import datetime, timedelta
import sqlite3
import threading
import time
import os

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)


# -----------------------
# Config
# -----------------------
POSITIVE_KEYWORDS = ['beats', 'raises', 'expands', 'up', 'gain', 'upgrade', 'record', 'surge']
NEWS_SCORE_THRESHOLD = 1
NEWS_WINDOW_DAYS = 3
NEWS_POLL_INTERVAL = 60 * 60  # 1 hour

DB_FILE = 'alerts.db'

# -----------------------
# Flask app
# -----------------------
app = Flask(__name__)

# -----------------------
# Database setup
# -----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            ticker TEXT,
            type TEXT,
            start_time TEXT,
            notified INTEGER,
            PRIMARY KEY (ticker, type)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS news (
            ticker TEXT,
            title TEXT,
            link TEXT,
            timestamp TEXT,
            PRIMARY KEY (ticker, title)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# -----------------------
# Helper functions
# -----------------------
def fetch_yahoo_news(ticker, count=5):
    rss_url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US'
    feed = feedparser.parse(rss_url)
    news_items = [(entry.title, entry.link) for entry in feed.entries[:count]]
    return news_items

def score_news(news_items):
    score = 0
    for title, _ in news_items:
        title_lower = title.lower()
        for kw in POSITIVE_KEYWORDS:
            if kw in title_lower:
                score += 1
    return score

def save_alert(ticker, alert_type):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    now_str = datetime.now().isoformat()
    c.execute('INSERT OR REPLACE INTO alerts (ticker, type, start_time, notified) VALUES (?, ?, ?, ?)',
              (ticker, alert_type, now_str, 0))
    conn.commit()
    conn.close()

def save_news(ticker, news_items):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for title, link in news_items:
        c.execute('INSERT OR IGNORE INTO news (ticker, title, link, timestamp) VALUES (?, ?, ?, ?)',
                  (ticker, title, link, datetime.now().isoformat()))
    conn.commit()
    conn.close()

# -----------------------
# Background news polling
# -----------------------
def news_polling_loop():
    while True:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute('SELECT ticker, type, start_time, notified FROM alerts')
        all_alerts = c.fetchall()
        now = datetime.now()

        for ticker, alert_type, start_time_str, notified in all_alerts:
            start_time = datetime.fromisoformat(start_time_str)
            if now > start_time + timedelta(days=NEWS_WINDOW_DAYS):
                # Expired alert
                c.execute('DELETE FROM alerts WHERE ticker=? AND type=?', (ticker, alert_type))
                continue

            if alert_type == 'premium_ready' and not notified:
                news_items = fetch_yahoo_news(ticker)
                save_news(ticker, news_items)
                score = score_news(news_items)
                if score >= NEWS_SCORE_THRESHOLD:
                    print(f"{ticker} - Positive news detected! Score={score}")
                    c.execute('UPDATE alerts SET notified=1 WHERE ticker=? AND type=?', (ticker, alert_type))

        conn.commit()
        conn.close()
        time.sleep(NEWS_POLL_INTERVAL)

threading.Thread(target=news_polling_loop, daemon=True).start()

# -----------------------
# TradingView webhook
# -----------------------
@app.route('/webhook/<ticker>/<alert_type>')
def tradingview_webhook(ticker, alert_type):
    save_alert(ticker, alert_type)
    if alert_type == 'premium_ready':
        news_items = fetch_yahoo_news(ticker)
        save_news(ticker, news_items)
    return f"Alert received: {ticker} ({alert_type})"

# -----------------------
# API endpoint for frontend
# -----------------------
@app.route('/api/alerts')
def api_alerts():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT ticker, type, start_time, notified FROM alerts')
    alerts_list = c.fetchall()

    data = []
    for ticker, alert_type, start_time_str, notified in alerts_list:
        c.execute('SELECT title, link FROM news WHERE ticker=? ORDER BY timestamp DESC', (ticker,))
        news_items = c.fetchall()
        score = score_news(news_items) if news_items else 0
        data.append({
            'ticker': ticker,
            'type': alert_type,
            'start_time': start_time_str,
            'notified': notified,
            'score': score,
            'news_items': [{'title': t, 'link': l} for t, l in news_items]
        })
    conn.close()
    return jsonify(data)


# -----------------------
# Frontend page
# -----------------------
@app.route('/')
def index():
    return render_template('alerts_dynamic.html')

# -----------------------
# Run Flask
# -----------------------
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)

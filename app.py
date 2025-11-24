from flask import Flask, render_template, jsonify, request
from flask_cors import CORS
import sqlite3
import threading
import time
from datetime import datetime, timedelta
import requests
import xml.etree.ElementTree as ET
import os

# -----------------------
# Config
# -----------------------
POSITIVE_KEYWORDS = [
    'beats', 'raises', 'expands', 'up', 'gain', 'upgrade', 'record', 'surge',
    'dividend', 'payout', 'increase', 'growth', 'exceeds', 'tops', 'improves',
    'profit', 'income', 'milestone', 'agreement', 'partnership', 'outperform',
    'revised up', 'guidance', 'strong', 'positive', 'surpass'
]

NEWS_SCORE_THRESHOLD = 1          # Minimum score to trigger Discord alert
NEWS_WINDOW_DAYS = 1              # Stop checking each alert after 1 day
NEWS_LOOKBACK_DAYS = 5            # Only consider news from the last 5 days
NEWS_POLL_INTERVAL = 10 * 60      # Check news every 10 minutes (600 seconds)

DB_FILE = 'alerts.db'
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")  # Webhook stored in env

# -----------------------
# Flask setup
# -----------------------
app = Flask(__name__)
CORS(app)

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
    """Fetch Yahoo Finance RSS news (Python 3.13 safe)."""
    url = f'https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US'
    r = requests.get(url)
    root = ET.fromstring(r.content)
    items = []
    for item in root.findall('.//item')[:count]:
        title = item.find('title').text
        link = item.find('link').text
        items.append((title, link))
    return items

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
# Discord integration
# -----------------------
def send_discord_alert(ticker, alert_type, news_items=None, score=None):
    if not DISCORD_WEBHOOK_URL:
        return
    content = f"**Alert:** {ticker} - {alert_type}\n"
    if news_items:
        content += f"Score: {score}\n"
        for title, link in news_items:
            content += f"- [{title}]({link})\n"
    try:
        requests.post(DISCORD_WEBHOOK_URL, json={"content": content})
    except Exception as e:
        print(f"Failed to send Discord message: {e}")

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
                news_items = fetch_yahoo_news(ticker, count=20)  # Fetch more to cover last 5 days
                # Filter for last 5 days only
                recent_news = []
                for title, link in news_items:
                    # Skip if already saved
                    c.execute('SELECT 1 FROM news WHERE ticker=? AND title=?', (ticker, title))
                    if c.fetchone():
                        continue
                    recent_news.append((title, link))

                if recent_news:
                    save_news(ticker, recent_news)
                    score = score_news(recent_news)
                    if score >= NEWS_SCORE_THRESHOLD:
                        print(f"{ticker} - Positive news detected! Score={score}")
                        c.execute('UPDATE alerts SET notified=1 WHERE ticker=? AND type=?', (ticker, alert_type))
                        # Send Discord notification
                        send_discord_alert(ticker, alert_type, news_items=recent_news, score=score)

        conn.commit()
        conn.close()
        time.sleep(NEWS_POLL_INTERVAL)


threading.Thread(target=news_polling_loop, daemon=True).start()

# -----------------------
# TradingView webhook
# -----------------------
@app.route('/webhook', methods=['POST'])
def tradingview_webhook():
    data = request.json
    ticker = data.get('ticker')
    alert_type = data.get('type')
    save_alert(ticker, alert_type)
    if alert_type == 'premium_ready':
        news_items = fetch_yahoo_news(ticker)
        save_news(ticker, news_items)
        # Send Discord notification
        send_discord_alert(ticker, alert_type, news_items=news_items, score=score_news(news_items))
    return jsonify({'status': 'success'}), 200

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


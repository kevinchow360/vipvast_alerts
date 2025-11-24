import requests, os

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")  # make sure this is set
requests.post(DISCORD_WEBHOOK_URL, json={"content": "**Test Alert:** AAPL - premium_ready\nScore: 2\n- [Apple beats earnings](https://finance.yahoo.com/news/apple-beats-earnings)"})
print("Test alert sent. Check your Discord channel.")

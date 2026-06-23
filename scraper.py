"""
Reddit Finanz-Agent – scraper.py
Läuft stündlich via GitHub Actions.
Schreibt Ergebnisse nach: docs/data.json  (von GitHub Pages serviert)
"""

import json
import re
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from collections import defaultdict

# ── Konfiguration ────────────────────────────────────────────────────────────

SUBREDDITS = [
    "Mauerstrassenwetten",
    "wallstreetbets",
    "Ameisenstrassenwetten",
]

SORT       = "hot"   # hot | new | top
LIMIT      = 50      # Posts pro Subreddit
OUTPUT     = "docs/data.json"

# Wörter die KEIN Ticker sind
SKIP = {
    "DD","YOLO","WSB","ETF","CEO","IPO","FDA","GDP","EUR","USD","GBP","CHF",
    "SPY","QQQ","PUT","CALL","BUY","SELL","HOLD","EPS","PE","ATH","ATL",
    "OP","FED","ECB","DAX","IMO","FOMO","DIY","USA","UK","EU","DE","AG",
    "SE","SA","NV","LTD","INC","PLC","LLC","EDIT","TL","DR","EV","AI","ML",
    "IT","TV","PC","AM","PM","OK","DM","TA","WTF","LMAO","LOL","OMG","PS",
    "IQ","HQ","HR","PR","CTO","CFO","COO","HOT","NEW","TOP","THE","AND",
    "FOR","YOU","ARE","NOT","BUT","ALL","CAN","GET","HAS","HAD","ITS","OUR",
    "NOW","MAY","USE","TWO","WAY","WHO","OIL","GAS","CAR","CAD","AUD","JPY",
    "DKK","NOK","SEK","PLN","RUB","CNY","HKD","SGD","MXN","BRL","INR",
    "DIV","ROE","ROA","YOY","QOQ","MOM","YTD","SMA","EMA","RSI","MACD",
    "ADX","ATR","OBV","VOL","AVG","MAX","MIN","SUM","NET","VAT","CASH",
    "RISK","BOND","NOTE","INFO","NEWS","POST","ASAP","TBA","TBC","TBD",
}

BULL_KW = [
    "moon","rocket","bullish","long","buy","kauf","steigt","rakete",
    "kursziel","ausbruch","breakout","squeeze","undervalued","günstig",
    "pump","upside","recovery","rebound","strong buy","accumulate",
    "oversold","nachkaufen","chance","potential","uptrend","gehebelt",
]

BEAR_KW = [
    "short","puts","bearish","crash","sell","verkauf","fällt","drop",
    "überbewertet","bubble","dump","leerverkauf","downside","resistance",
    "overbought","breakdown","decline","falling","schwach","warnung",
    "vorsicht","verlust",
]

# ── Ticker-Extraktion ─────────────────────────────────────────────────────────

TICKER_RE = re.compile(r'\$([A-Z]{1,5})|(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])')

def extract_tickers(text: str) -> list[str]:
    found = set()
    for m in TICKER_RE.finditer(text):
        t = m.group(1) or m.group(2)
        if t and t not in SKIP and 2 <= len(t) <= 5:
            found.add(t)
    return list(found)

def score_sentiment(text: str) -> tuple[int, int]:
    t = text.lower()
    bull = sum(1 for kw in BULL_KW if kw in t)
    bear = sum(1 for kw in BEAR_KW if kw in t)
    return bull, bear

# ── Reddit-Fetch ──────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": "RedditFinanzAgent/1.0 (GitHub Actions; educational)",
}

def fetch_subreddit(sub: str, sort: str = "hot", limit: int = 50) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/{sort}.json?limit={limit}&raw_json=1"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
        posts = [child["data"] for child in data["data"]["children"]]
        print(f"  ✓ r/{sub}: {len(posts)} Posts geladen")
        return posts
    except urllib.error.HTTPError as e:
        print(f"  ✗ r/{sub}: HTTP {e.code} – {e.reason}")
        return []
    except Exception as e:
        print(f"  ✗ r/{sub}: {e}")
        return []

# ── Hauptlogik ────────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*50}")
    print(f"Reddit Finanz-Agent  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}")

    ticker_data: dict[str, dict] = defaultdict(lambda: {
        "bull": 0, "bear": 0, "mentions": 0,
        "engagement": 0, "sources": [], "titles": [],
    })

    total_posts = 0
    sub_results = []

    for sub in SUBREDDITS:
        print(f"\nLade r/{sub}...")
        posts = fetch_subreddit(sub, SORT, LIMIT)
        total_posts += len(posts)
        sub_results.append({"name": sub, "posts": len(posts)})
        time.sleep(2)  # Rate-limit: Reddit mag keine schnellen Anfragen

        for p in posts:
            text = f"{p.get('title','')} {p.get('selftext','')}"
            tickers = extract_tickers(text)
            bull, bear = score_sentiment(text)
            engagement = p.get("score", 0) + p.get("num_comments", 0) * 2

            for ticker in tickers:
                d = ticker_data[ticker]
                d["bull"]       += bull
                d["bear"]       += bear
                d["mentions"]   += 1
                d["engagement"] += engagement
                if sub not in d["sources"]:
                    d["sources"].append(sub)
                if len(d["titles"]) < 3:
                    title = p.get("title", "")[:100]
                    if title:
                        d["titles"].append(title)

    # Ranking: mind. 2 Mentions, sortiert nach Engagement + Mentions
    ranked = sorted(
        [(t, d) for t, d in ticker_data.items() if d["mentions"] >= 2],
        key=lambda x: x[1]["engagement"] + x[1]["mentions"] * 15,
        reverse=True,
    )[:10]

    recommendations = []
    for ticker, d in ranked:
        net = d["bull"] - d["bear"]
        if net > 1:
            signal = "bullish"
        elif net < -1:
            signal = "bearish"
        else:
            signal = "neutral"

        recommendations.append({
            "ticker":     ticker,
            "signal":     signal,
            "sentiment":  net,
            "mentions":   d["mentions"],
            "engagement": round(d["engagement"]),
            "sources":    d["sources"],
            "titles":     d["titles"],
        })

    output = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "total_posts":     total_posts,
        "unique_tickers":  len(ticker_data),
        "subreddits":      sub_results,
        "recommendations": recommendations,
    }

    import os
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✓ {len(recommendations)} Empfehlungen gespeichert → {OUTPUT}")
    print(f"✓ {total_posts} Posts analysiert, {len(ticker_data)} Ticker erkannt")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    run()

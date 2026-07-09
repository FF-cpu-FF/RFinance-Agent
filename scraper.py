"""
Reddit Finanz-Agent – scraper.py (RSS Version)
Läuft stündlich via GitHub Actions. Kein API-Key nötig!
"""

import json
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import defaultdict
import os

SUBREDDITS = ["Mauerstrassenwetten", "wallstreetbets", "Ameisenstrassenwetten"]
SORT   = "hot"
LIMIT  = 50
OUTPUT = "docs/data.json"

SKIP = {
    "DD","YOLO","WSB","ETF","CEO","IPO","FDA","GDP","EUR","USD","GBP","CHF",
    "SPY","QQQ","PUT","CALL","BUY","SELL","HOLD","EPS","PE","ATH","ATL","OP",
    "FED","ECB","DAX","IMO","FOMO","DIY","USA","UK","EU","DE","AG","SE","SA",
    "NV","LTD","INC","PLC","LLC","EDIT","TL","DR","EV","AI","ML","IT","TV",
    "PC","AM","PM","OK","DM","TA","WTF","LMAO","LOL","OMG","PS","IQ","HQ",
    "HR","PR","CTO","CFO","COO","HOT","NEW","TOP","THE","AND","FOR","YOU",
    "ARE","NOT","BUT","ALL","CAN","GET","HAS","HAD","ITS","OUR","NOW","MAY",
    "USE","TWO","WAY","WHO","OIL","GAS","CAR","CAD","AUD","JPY","DKK","NOK",
    "SEK","PLN","CNY","HKD","SGD","MXN","BRL","INR","DIV","ROE","ROA","YOY",
    "QOQ","MOM","YTD","SMA","EMA","RSI","MACD","VOL","AVG","MAX","MIN","NET",
    "VAT","CASH","RISK","BOND","INFO","NEWS","POST","KI","US","EU","VW","BMW",
}

BULL_KW = ["moon","rocket","bullish","long","buy","kauf","steigt","rakete",
    "kursziel","ausbruch","breakout","squeeze","undervalued","günstig","pump",
    "upside","recovery","rebound","accumulate","oversold","nachkaufen","chance",
    "potential","uptrend","kaufen","stark","wachstum","beat","übertrifft"]

BEAR_KW = ["short","puts","bearish","crash","sell","verkauf","fällt","drop",
    "überbewertet","bubble","dump","leerverkauf","downside","overbought",
    "breakdown","decline","falling","schwach","warnung","verlust","miss",
    "verfehlt","gewinnwarnung","pleite","insolvenz"]

TICKER_RE = re.compile(r'\$([A-Z]{1,5})|(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])')

def extract_tickers(text):
    found = set()
    for m in TICKER_RE.finditer(text):
        t = m.group(1) or m.group(2)
        if t and t not in SKIP and 2 <= len(t) <= 5:
            found.add(t)
    return list(found)

def score_sentiment(text):
    t = text.lower()
    bull = sum(1 for kw in BULL_KW if kw in t)
    bear = sum(1 for kw in BEAR_KW if kw in t)
    return bull, bear

def fetch_subreddit_rss(sub, sort="hot", limit=50):
    candidates = [
        f"https://www.reddit.com/r/{sub}/{sort}.rss?limit={limit}",
        f"https://old.reddit.com/r/{sub}/{sort}.rss?limit={limit}",
    ]
    headers = {"User-Agent": "Mozilla/5.0 (compatible; FinanzAgent/1.0)"}
    for candidate_url in candidates:
        try:
            req = urllib.request.Request(candidate_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8")
            root = ET.fromstring(content)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            posts = []
            for entry in root.findall("atom:entry", ns):
                title = entry.findtext("atom:title", "", ns)
                content_el = entry.find("atom:content", ns)
                body = re.sub(r"<[^>]+>", " ", (content_el.text or "") if content_el is not None else "")
                posts.append({"title": title, "selftext": body})
            if posts:
                print(f"  ✓ r/{sub}: {len(posts)} Posts geladen")
                return posts
        except Exception as e:
            print(f"  ✗ r/{sub} ({candidate_url}): {e}")
    return []

def run():
    print(f"\n{'='*50}")
    print(f"Reddit Finanz-Agent  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}")

    ticker_data = defaultdict(lambda: {
        "bull": 0, "bear": 0, "mentions": 0,
        "engagement": 0, "sources": [], "titles": [],
    })

    total_posts = 0
    sub_results = []

    for sub in SUBREDDITS:
        print(f"\nLade r/{sub}...")
        posts = fetch_subreddit_rss(sub, SORT, LIMIT)
        total_posts += len(posts)
        sub_results.append({"name": sub, "posts": len(posts)})
        time.sleep(6)

        for p in posts:
            text = f"{p.get('title','')} {p.get('selftext','')}"
            tickers = extract_tickers(text)
            bull, bear = score_sentiment(text)

            for ticker in tickers:
                d = ticker_data[ticker]
                d["bull"]       += bull
                d["bear"]       += bear
                d["mentions"]   += 1
                d["engagement"] += bull + bear + 1
                if sub not in d["sources"]:
                    d["sources"].append(sub)
                if len(d["titles"]) < 3:
                    title = p.get("title", "")[:100]
                    if title:
                        d["titles"].append(title)

    ranked = sorted(
        [(t, d) for t, d in ticker_data.items() if d["mentions"] >= 2],
        key=lambda x: x[1]["engagement"] + x[1]["mentions"] * 15,
        reverse=True,
    )[:10]

    recommendations = []
    for ticker, d in ranked:
        net = d["bull"] - d["bear"]
        signal = "bullish" if net > 1 else "bearish" if net < -1 else "neutral"
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

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*50}")
    print(f"✓ {len(recommendations)} Empfehlungen → {OUTPUT}")
    print(f"✓ {total_posts} Posts, {len(ticker_data)} Ticker")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    run()

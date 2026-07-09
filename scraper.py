"""
Reddit Finanz-Agent v2 – scraper.py
Reddit = Primärquelle. Zusätzlich pro Top-Ticker:
  - Kursdaten (Yahoo Finance Chart API, kostenlos, kein Key)
  - News-Headlines (Yahoo Finance RSS)
  - Technik-Signale (SMA20, Trend 7d/1M)
  - Trend vs. letztem Scan (Mentions-Delta)
  - Regelbasierte Vergleichsanalyse (bestätigt / widerspricht / relativiert Reddit)
Läuft via GitHub Actions. Nutzt REDDIT_FEED_URL Secret gegen Rate-Limits.
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

# ── Konfiguration ────────────────────────────────────────────────────────────

SUBREDDITS = [
    "Mauerstrassenwetten",
    "wallstreetbets",
    "Ameisenstrassenwetten",
    "TrumpsTrades",
    "wallstreetbetsGER",
]

SORT        = "hot"
LIMIT       = 50
OUTPUT      = "docs/data.json"
TOP_N       = 10   # für so viele Ticker werden Kurse/News geladen
UA          = {"User-Agent": "Mozilla/5.0 (compatible; FinanzAgent/2.0)"}

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
    "VAT","CASH","RISK","BOND","INFO","NEWS","POST","KI","US","VW",
    "TLDR","MSW","AWS","ASW","WSBG","MSFT2","GER","IST","DAS","DER","DIE",
    "UND","MIT","VON","AUF","ZUM","ZUR","EIN","WIE","WAS","WER","NUR","ABER",
}

BULL_KW = ["moon","rocket","bullish","long","buy","kauf","steigt","rakete",
    "kursziel","ausbruch","breakout","squeeze","undervalued","günstig","pump",
    "upside","recovery","rebound","accumulate","oversold","nachkaufen","chance",
    "potential","uptrend","kaufen","stark","wachstum","beat","übertrifft","calls"]

BEAR_KW = ["short","puts","bearish","crash","sell","verkauf","fällt","drop",
    "überbewertet","bubble","dump","leerverkauf","downside","overbought",
    "breakdown","decline","falling","schwach","warnung","verlust","miss",
    "verfehlt","gewinnwarnung","pleite","insolvenz","bagholder"]

TICKER_RE = re.compile(r'\$([A-Z]{1,5})|(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])')


# ── Reddit ───────────────────────────────────────────────────────────────────

def get_feed_auth():
    feed_url = os.environ.get("REDDIT_FEED_URL", "")
    m = re.search(r'feed=([^&]+)&user=([^&\s]+)', feed_url)
    if m:
        return f"feed={m.group(1)}&user={m.group(2)}"
    return ""


def fetch_subreddit_rss(sub, sort="hot", limit=50):
    auth = get_feed_auth()
    candidates = []
    if auth:
        candidates.append(f"https://www.reddit.com/r/{sub}/{sort}.rss?limit={limit}&{auth}")
        candidates.append(f"https://old.reddit.com/r/{sub}/{sort}.rss?limit={limit}&{auth}")
    candidates.append(f"https://www.reddit.com/r/{sub}/{sort}.rss?limit={limit}")

    for candidate_url in candidates:
        try:
            req = urllib.request.Request(candidate_url, headers=UA)
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
        except Exception:
            print(f"  ✗ r/{sub}: Fehler, versuche nächste URL...")
        time.sleep(3)
    return []


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


# ── Kursdaten (Yahoo Finance Chart API) ─────────────────────────────────────

def yahoo_chart(ticker, rng, interval):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rng}&interval={interval}")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        result = data["chart"]["result"][0]
        ts     = result.get("timestamp", [])
        closes = result["indicators"]["quote"][0].get("close", [])
        series = [
            {"t": t, "c": round(c, 2)}
            for t, c in zip(ts, closes) if c is not None
        ]
        meta   = result.get("meta", {})
        return series, meta
    except Exception:
        return [], {}


def fetch_price_data(ticker):
    """Holt 1d/5d/1M-Serien + berechnet Kennzahlen."""
    out = {"available": False}
    series_1mo, meta = yahoo_chart(ticker, "1mo", "1d")
    if not series_1mo:
        return out
    time.sleep(0.5)
    series_1d, _ = yahoo_chart(ticker, "1d", "15m")
    time.sleep(0.5)
    series_5d, _ = yahoo_chart(ticker, "5d", "60m")

    closes = [p["c"] for p in series_1mo]
    price  = closes[-1]
    out["available"]  = True
    out["price"]      = price
    out["currency"]   = meta.get("currency", "USD")
    out["name"]       = meta.get("longName") or meta.get("shortName") or ticker
    out["chart_1d"]   = series_1d[-40:]
    out["chart_5d"]   = series_5d[-60:]
    out["chart_1mo"]  = series_1mo

    # Kennzahlen
    def pct(a, b):
        return round((a - b) / b * 100, 2) if b else 0.0

    out["chg_1d"]  = pct(price, series_1d[0]["c"])  if series_1d  else 0.0
    out["chg_7d"]  = pct(price, closes[-6])          if len(closes) >= 6 else 0.0
    out["chg_1mo"] = pct(price, closes[0])           if len(closes) >= 2 else 0.0

    sma20 = sum(closes[-20:]) / min(len(closes), 20)
    out["sma20_dist"] = pct(price, sma20)
    return out


# ── News (Yahoo Finance RSS) ─────────────────────────────────────────────────

def fetch_news(ticker, max_items=3):
    url = (f"https://feeds.finance.yahoo.com/rss/2.0/headline"
           f"?s={ticker}&region=US&lang=en-US")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link  = item.findtext("link", "")
            pub   = item.findtext("pubDate", "")
            if title:
                items.append({"title": title[:140], "link": link, "date": pub[:16]})
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []


# ── Vergleichsanalyse (regelbasiert) ─────────────────────────────────────────

def build_comparison(reddit_signal, sentiment, price):
    """
    Gegencheck: Was sagt der Markt zur Reddit-Stimmung?
    verdict: 'bestätigt' | 'widerspricht' | 'relativiert' | 'unbekannt'
    """
    if not price.get("available"):
        return {
            "verdict": "unbekannt",
            "points": ["Keine Kursdaten verfügbar – Ticker evtl. kein US-Symbol."],
        }

    points  = []
    bull_ev = 0  # externe Evidenz bullisch
    bear_ev = 0

    c7, c30, sma = price["chg_7d"], price["chg_1mo"], price["sma20_dist"]

    if c7 > 3:
        points.append(f"Kurs +{c7}% über 7 Tage – Aufwärtsmomentum.")
        bull_ev += 1
    elif c7 < -3:
        points.append(f"Kurs {c7}% über 7 Tage – Abwärtsdruck.")
        bear_ev += 1
    else:
        points.append(f"Kurs seitwärts über 7 Tage ({c7:+}%).")

    if c30 > 8:
        points.append(f"Starker Monat: {c30:+}%.")
        bull_ev += 1
    elif c30 < -8:
        points.append(f"Schwacher Monat: {c30:+}%.")
        bear_ev += 1

    if sma > 5:
        points.append(f"{sma:+}% über SMA20 – evtl. kurzfristig überkauft.")
        bear_ev += 0.5
    elif sma < -5:
        points.append(f"{sma:+}% unter SMA20 – technisch angeschlagen oder Einstiegszone.")

    reddit_bull = sentiment > 1
    reddit_bear = sentiment < -1

    if reddit_bull and bull_ev > bear_ev:
        verdict = "bestätigt"
        points.append("Marktlage stützt die bullische Reddit-Stimmung.")
    elif reddit_bull and bear_ev > bull_ev:
        verdict = "widerspricht"
        points.append("Reddit ist bullisch, aber der Kurs zeigt Schwäche – Hype-Risiko.")
    elif reddit_bear and bear_ev > bull_ev:
        verdict = "bestätigt"
        points.append("Marktlage stützt die skeptische Reddit-Stimmung.")
    elif reddit_bear and bull_ev > bear_ev:
        verdict = "widerspricht"
        points.append("Reddit ist bearisch, aber der Kurs hält sich stark.")
    else:
        verdict = "relativiert"
        points.append("Externe Lage uneindeutig – Signal mit Vorsicht behandeln.")

    return {"verdict": verdict, "points": points}


def final_recommendation(sentiment, verdict):
    """Kaufen / Beobachten / Verkaufen aus Reddit-Signal + Gegencheck."""
    if sentiment > 1 and verdict == "bestätigt":
        return "kaufen"
    if sentiment < -1 and verdict == "bestätigt":
        return "verkaufen"
    return "beobachten"


# ── Trend vs. letzter Scan ───────────────────────────────────────────────────

def load_previous_mentions():
    try:
        with open(OUTPUT, encoding="utf-8") as f:
            prev = json.load(f)
        return {r["ticker"]: r.get("mentions", 0)
                for r in prev.get("recommendations", [])}
    except Exception:
        return {}


# ── Hauptlogik ───────────────────────────────────────────────────────────────

def run():
    print(f"\n{'='*50}")
    print(f"Reddit Finanz-Agent v2  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}")

    prev_mentions = load_previous_mentions()

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
                    title = p.get("title", "")[:110]
                    if title:
                        d["titles"].append(title)

    ranked = sorted(
        [(t, d) for t, d in ticker_data.items() if d["mentions"] >= 2],
        key=lambda x: x[1]["engagement"] + x[1]["mentions"] * 15,
        reverse=True,
    )[:TOP_N]

    print(f"\nLade Kurse & News für Top {len(ranked)} Ticker...")
    recommendations = []
    for ticker, d in ranked:
        net = d["bull"] - d["bear"]
        reddit_signal = "bullish" if net > 1 else "bearish" if net < -1 else "neutral"

        price = fetch_price_data(ticker)
        time.sleep(1)
        news = fetch_news(ticker) if price.get("available") else []
        time.sleep(1)

        comparison = build_comparison(reddit_signal, net, price)
        empfehlung = final_recommendation(net, comparison["verdict"])

        delta = d["mentions"] - prev_mentions.get(ticker, 0)

        status = "✓" if price.get("available") else "○"
        print(f"  {status} {ticker}: {empfehlung} ({comparison['verdict']})")

        recommendations.append({
            "ticker":        ticker,
            "name":          price.get("name", ticker),
            "signal":        reddit_signal,
            "empfehlung":    empfehlung,
            "sentiment":     net,
            "mentions":      d["mentions"],
            "mentions_delta": delta,
            "engagement":    round(d["engagement"]),
            "sources":       d["sources"],
            "titles":        d["titles"],
            "price":         price,
            "news":          news,
            "comparison":    comparison,
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

"""
Reddit Finanz-Agent v3 – scraper.py
Reddit bleibt Primärquelle. Neu in v3:
  - Themen-Extraktion ("Warum diskutiert Reddit diese Aktie?")
  - Bull Case / Bear Case aus den Posts
  - Confidence Score (0-100)
  - News-Einstufung (positiv/neutral/negativ)
  - Automatisches KI-Fazit (regelbasiert formuliert)
Läuft via GitHub Actions. Nutzt REDDIT_FEED_URL Secret.
"""

import json
import re
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from collections import defaultdict, Counter
import os

# ── Konfiguration ────────────────────────────────────────────────────────────

SUBREDDITS = [
    "Mauerstrassenwetten",
    "wallstreetbets",
    "Ameisenstrassenwetten",
    "TrumpsTrades",
    "wallstreetbetsGER",
]

SORT   = "hot"
LIMIT  = 50
OUTPUT = "docs/data.json"
TOP_N  = 10
UA     = {"User-Agent": "Mozilla/5.0 (compatible; FinanzAgent/3.0)"}

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
    "TLDR","MSW","AWS","ASW","WSBG","GER","IST","DAS","DER","DIE","UND","MIT",
    "VON","AUF","ZUM","ZUR","EIN","WIE","WAS","WER","NUR","ABER","HBM","GPU",
    "CPU","API","LFG","IMHO","BTFD","HODL",
}

BULL_KW = ["moon","rocket","bullish","long","buy","kauf","steigt","rakete",
    "kursziel","ausbruch","breakout","squeeze","undervalued","günstig","pump",
    "upside","recovery","rebound","accumulate","oversold","nachkaufen","chance",
    "potential","uptrend","kaufen","stark","wachstum","beat","übertrifft","calls"]

BEAR_KW = ["short","puts","bearish","crash","sell","verkauf","fällt","drop",
    "überbewertet","bubble","dump","leerverkauf","downside","overbought",
    "breakdown","decline","falling","schwach","warnung","verlust","miss",
    "verfehlt","gewinnwarnung","pleite","insolvenz","bagholder"]

# Lesbare Labels für Bull/Bear-Cases
KW_LABELS = {
    "squeeze": "Short-Squeeze-Spekulation", "moon": "Kursfantasie", "rocket": "Kursfantasie",
    "breakout": "Chart-Ausbruch", "ausbruch": "Chart-Ausbruch",
    "undervalued": "Unterbewertung", "günstig": "Unterbewertung",
    "kursziel": "Erhöhte Kursziele", "beat": "Zahlen über Erwartung",
    "übertrifft": "Zahlen über Erwartung", "wachstum": "Wachstumsstory",
    "recovery": "Erholungs-These", "rebound": "Erholungs-These",
    "oversold": "Überverkauft-These", "nachkaufen": "Nachkauf-Welle",
    "calls": "Call-Optionen-Aktivität", "puts": "Put-Optionen-Aktivität",
    "short": "Short-Positionierung", "leerverkauf": "Short-Positionierung",
    "crash": "Crash-Warnungen", "bubble": "Blasen-Warnung",
    "überbewertet": "Überbewertungs-Kritik", "overbought": "Überkauft-Warnung",
    "gewinnwarnung": "Gewinnwarnung", "miss": "Zahlen unter Erwartung",
    "verfehlt": "Zahlen unter Erwartung", "insolvenz": "Insolvenz-Sorgen",
    "pleite": "Insolvenz-Sorgen", "bagholder": "Verlust-Frust",
    "verlust": "Verlust-Meldungen", "warnung": "Warnende Stimmen",
}

# Stopwörter für Themen-Extraktion
TOPIC_STOP = {
    "the","and","for","with","this","that","from","have","will","been","they",
    "what","when","your","just","like","about","after","into","over","than",
    "der","die","das","und","mit","von","auf","für","ist","ein","eine","nach",
    "über","beim","wird","sind","hat","noch","mehr","auch","aber","wenn","wie",
    "ich","wir","ihr","euch","mein","sein","kein","nur","zum","zur","bei",
    "reddit","aktie","aktien","stock","stocks","heute","today","daily","thread",
    "diskussion","discussion","frage","question","warum","why","alle","best",
}

TICKER_RE = re.compile(r'\$([A-Z]{1,5})|(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])')

NEWS_POS = ["beat","raises","upgrade","surge","rally","record","growth","wins",
    "profit","strong","boost","soars","jumps","erhöht","übertrifft","rekord","gewinn"]
NEWS_NEG = ["miss","cuts","downgrade","falls","drops","lawsuit","probe","warning",
    "weak","layoff","plunge","sinks","recall","senkt","verfehlt","warnung","klage","verlust"]


# ── Reddit ───────────────────────────────────────────────────────────────────

def get_feed_auth():
    feed_url = os.environ.get("REDDIT_FEED_URL", "")
    m = re.search(r'feed=([^&]+)&user=([^&\s]+)', feed_url)
    return f"feed={m.group(1)}&user={m.group(2)}" if m else ""


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


def matched_keywords(text, kws):
    t = text.lower()
    return [kw for kw in kws if kw in t]


# ── Kursdaten ────────────────────────────────────────────────────────────────

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
        series = [{"t": t, "c": round(c, 2)} for t, c in zip(ts, closes) if c is not None]
        return series, result.get("meta", {})
    except Exception:
        return [], {}


def fetch_price_data(ticker):
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

    def pct(a, b):
        return round((a - b) / b * 100, 2) if b else 0.0

    out.update({
        "available": True,
        "price":     price,
        "currency":  meta.get("currency", "USD"),
        "name":      meta.get("longName") or meta.get("shortName") or ticker,
        "chart_1d":  series_1d[-40:],
        "chart_5d":  series_5d[-60:],
        "chart_1mo": series_1mo,
        "chg_1d":    pct(price, series_1d[0]["c"]) if series_1d else 0.0,
        "chg_7d":    pct(price, closes[-6]) if len(closes) >= 6 else 0.0,
        "chg_1mo":   pct(price, closes[0]) if len(closes) >= 2 else 0.0,
    })
    sma20 = sum(closes[-20:]) / min(len(closes), 20)
    out["sma20_dist"] = pct(price, sma20)
    return out


# ── News ─────────────────────────────────────────────────────────────────────

def classify_headline(title):
    t = title.lower()
    if any(k in t for k in NEWS_POS):
        return "pos"
    if any(k in t for k in NEWS_NEG):
        return "neg"
    return "neu"


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
                items.append({
                    "title": title[:140], "link": link,
                    "date": pub[:16], "tone": classify_headline(title),
                })
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []


# ── Analyse-Bausteine ────────────────────────────────────────────────────────

def extract_topics(titles, max_topics=4):
    """Häufigste sinnvolle Wörter aus den Post-Titeln = Diskussionsthemen."""
    words = []
    for title in titles:
        for w in re.findall(r"[A-Za-zÄÖÜäöüß\-]{4,}", title):
            wl = w.lower()
            if wl not in TOPIC_STOP and not wl.isupper():
                words.append(w if w[0].isupper() else wl)
    common = Counter(w.lower() for w in words).most_common(max_topics)
    # Original-Schreibweise bevorzugen
    result = []
    for word, _ in common:
        original = next((w for w in words if w.lower() == word), word)
        result.append(original.capitalize() if original.islower() else original)
    return result


def build_cases(bull_hits, bear_hits):
    def labelize(hits, max_n=3):
        labels = []
        for kw, _ in Counter(hits).most_common():
            label = KW_LABELS.get(kw, kw.capitalize())
            if label not in labels:
                labels.append(label)
            if len(labels) >= max_n:
                break
        return labels
    return labelize(bull_hits), labelize(bear_hits)


def build_comparison(sentiment, price):
    if not price.get("available"):
        return {"verdict": "unbekannt",
                "points": ["Keine Kursdaten verfügbar – Ticker evtl. kein US-Symbol."]}

    points, bull_ev, bear_ev = [], 0.0, 0.0
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
        points.append(f"{sma:+}% über SMA20 – kurzfristig evtl. überkauft.")
        bear_ev += 0.5
    elif sma < -5:
        points.append(f"{sma:+}% unter SMA20 – technisch angeschlagen.")

    reddit_bull, reddit_bear = sentiment > 1, sentiment < -1
    if reddit_bull and bull_ev > bear_ev:
        verdict = "bestätigt"; points.append("Marktlage stützt die bullische Reddit-Stimmung.")
    elif reddit_bull and bear_ev > bull_ev:
        verdict = "widerspricht"; points.append("Reddit bullisch, Kurs zeigt Schwäche – Hype-Risiko.")
    elif reddit_bear and bear_ev > bull_ev:
        verdict = "bestätigt"; points.append("Marktlage stützt die skeptische Reddit-Stimmung.")
    elif reddit_bear and bull_ev > bear_ev:
        verdict = "widerspricht"; points.append("Reddit bearisch, aber der Kurs hält sich stark.")
    else:
        verdict = "relativiert"; points.append("Externe Lage uneindeutig – Signal mit Vorsicht behandeln.")

    return {"verdict": verdict, "points": points}


def compute_confidence(mentions, sentiment, verdict, price_available):
    score = 45
    score += min(mentions * 3, 18)             # Diskussionsbreite
    score += min(abs(sentiment) * 3, 15)       # Signalstärke
    score += {"bestätigt": 18, "relativiert": 4,
              "widerspricht": -12, "unbekannt": -8}.get(verdict, 0)
    if not price_available:
        score -= 5
    return max(8, min(95, score))


def final_recommendation(sentiment, verdict):
    if sentiment > 1 and verdict == "bestätigt":
        return "kaufen"
    if sentiment < -1 and verdict == "bestätigt":
        return "verkaufen"
    return "beobachten"


def build_fazit(ticker, name, sentiment, verdict, rec, price, mentions, delta):
    """Regelbasiert formuliertes KI-Fazit (3-4 Sätze)."""
    s = []
    mood = ("deutlich bullisch" if sentiment > 3 else "bullisch" if sentiment > 1
            else "deutlich bearisch" if sentiment < -3 else "bearisch" if sentiment < -1
            else "gemischt")
    trend = (f" mit steigender Dynamik (+{delta} Mentions)" if delta > 1
             else f" bei abnehmender Aufmerksamkeit ({delta} Mentions)" if delta < -1 else "")
    s.append(f"Reddit diskutiert {name or ticker} aktuell {mood} ({mentions} Mentions{trend}).")

    if verdict == "bestätigt":
        s.append("Die Marktdaten stützen die Reddit-Stimmung: Kursverlauf und Momentum zeigen in dieselbe Richtung.")
    elif verdict == "widerspricht":
        s.append("Der Marktabgleich widerspricht jedoch: Kursverlauf und Momentum passen nicht zur Reddit-Stimmung – erhöhtes Hype-Risiko.")
    elif verdict == "relativiert":
        s.append("Der Marktabgleich liefert kein klares Bild – die externe Lage relativiert das Reddit-Signal.")
    else:
        s.append("Ein Marktabgleich war mangels Kursdaten nicht möglich.")

    if price.get("available"):
        sma = price["sma20_dist"]
        if sma > 5:
            s.append(f"Kurzfristig notiert der Kurs {sma:+}% über dem 20-Tage-Schnitt – eine Konsolidierung ist möglich.")
        elif sma < -5:
            s.append(f"Der Kurs liegt {sma:+}% unter dem 20-Tage-Schnitt – technisch angeschlagen, aber potenzielle Einstiegszone.")

    advice = {"kaufen": "Insgesamt erscheint eine Kaufposition vertretbar – mit engem Risikomanagement.",
              "verkaufen": "Insgesamt spricht die Lage eher für Zurückhaltung oder Gewinnmitnahmen.",
              "beobachten": "Eine Beobachtungsposition erscheint aktuell sinnvoller als ein aggressiver Einstieg."}[rec]
    s.append(advice)
    return " ".join(s)


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
    print(f"Reddit Finanz-Agent v3  |  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*50}")

    prev_mentions = load_previous_mentions()

    ticker_data = defaultdict(lambda: {
        "bull": 0, "bear": 0, "mentions": 0, "engagement": 0,
        "sources": [], "titles": [], "bull_hits": [], "bear_hits": [],
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
            tickers   = extract_tickers(text)
            bull_hits = matched_keywords(text, BULL_KW)
            bear_hits = matched_keywords(text, BEAR_KW)

            for ticker in tickers:
                d = ticker_data[ticker]
                d["bull"]       += len(bull_hits)
                d["bear"]       += len(bear_hits)
                d["mentions"]   += 1
                d["engagement"] += len(bull_hits) + len(bear_hits) + 1
                d["bull_hits"]  += bull_hits
                d["bear_hits"]  += bear_hits
                if sub not in d["sources"]:
                    d["sources"].append(sub)
                if len(d["titles"]) < 6:
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

        comparison = build_comparison(net, price)
        rec        = final_recommendation(net, comparison["verdict"])
        delta      = d["mentions"] - prev_mentions.get(ticker, 0)
        conf       = compute_confidence(d["mentions"], net,
                                        comparison["verdict"], price.get("available", False))
        topics     = extract_topics(d["titles"])
        bull_case, bear_case = build_cases(d["bull_hits"], d["bear_hits"])
        fazit      = build_fazit(ticker, price.get("name", ticker), net,
                                 comparison["verdict"], rec, price,
                                 d["mentions"], delta)

        print(f"  {'✓' if price.get('available') else '○'} {ticker}: "
              f"{rec} · {comparison['verdict']} · {conf}%")

        recommendations.append({
            "ticker":         ticker,
            "name":           price.get("name", ticker),
            "signal":         reddit_signal,
            "empfehlung":     rec,
            "confidence":     conf,
            "sentiment":      net,
            "mentions":       d["mentions"],
            "mentions_delta": delta,
            "engagement":     round(d["engagement"]),
            "sources":        d["sources"],
            "titles":         d["titles"][:3],
            "topics":         topics,
            "bull_case":      bull_case,
            "bear_case":      bear_case,
            "price":          price,
            "news":           news,
            "comparison":     comparison,
            "fazit":          fazit,
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


"""
Reddit Finanz-Agent v8.1 – scraper.py
v4-Features (Reddit-Signal, Marktabgleich, GitHub-Models-KI-Fazit) PLUS:
  - Hype Engine: Mentions-Timeline über mehrere Tage (docs/history.json)
  - Momentum Score (0-100) aus Diskussions-Wachstum
  - Hype vs. nachhaltiger Trend Einstufung
  - "Gründe für den Anstieg" (KI-generiert, mit Fallback)
  - Signal Quality Grade (A+ bis D) inkl. Meme-Erkennung
  - Reddit vs. Markt Vergleich
  - Historische Empfehlungen + Performance-Auswertung + Trefferquote
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

SORT    = "hot"
LIMIT   = 50
OUTPUT  = "docs/data.json"
HISTORY = "docs/history.json"
TOP_N   = 8
MAX_HIST_PRICE_FETCH = 12   # max. Kursabrufe für historische Auswertung
UA      = {"User-Agent": "Mozilla/5.0 (compatible; FinanzAgent/5.0)"}

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


def quick_price(ticker):
    """Nur aktueller Kurs – für historische Performance-Auswertung."""
    series, _ = yahoo_chart(ticker, "5d", "1d")
    return series[-1]["c"] if series else None


# ── News ─────────────────────────────────────────────────────────────────────

def classify_headline(title):
    t = title.lower()
    if any(k in t for k in NEWS_POS):
        return "pos"
    if any(k in t for k in NEWS_NEG):
        return "neg"
    return "neu"


def fetch_news(ticker, max_items=5):
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
                items.append({"title": title[:140], "link": link,
                              "date": pub[:16], "tone": classify_headline(title)})
            if len(items) >= max_items:
                break
        return items
    except Exception:
        return []


# ── Analyse-Bausteine (v3/v4) ────────────────────────────────────────────────

def extract_topics(titles, max_topics=4):
    words = []
    for title in titles:
        for w in re.findall(r"[A-Za-zÄÖÜäöüß\-]{4,}", title):
            wl = w.lower()
            if wl not in TOPIC_STOP and not wl.isupper():
                words.append(w if w[0].isupper() else wl)
    common = Counter(w.lower() for w in words).most_common(max_topics)
    result = []
    for word, _ in common:
        original = next((w for w in words if w.lower() == word), word)
        result.append(original.capitalize() if original.islower() else original)
    return result


def build_cases(bull_hits, bear_hits):
    def labelize(hits, max_n=3):
        labels = []
        for kw, _ in Counter(hits).most_common():
            label = KW_LABELS.get(kw)
            if label and label not in labels:
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
    score += min(mentions * 3, 18)
    score += min(abs(sentiment) * 3, 15)
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
    s = []
    mood = ("deutlich bullisch" if sentiment > 3 else "bullisch" if sentiment > 1
            else "deutlich bearisch" if sentiment < -3 else "bearisch" if sentiment < -1
            else "gemischt")
    trend = (f" mit steigender Dynamik (+{delta} Mentions)" if delta > 1
             else f" bei abnehmender Aufmerksamkeit ({delta} Mentions)" if delta < -1 else "")
    s.append(f"Reddit diskutiert {name or ticker} aktuell {mood} ({mentions} Mentions{trend}).")

    if verdict == "bestätigt":
        s.append("Die Marktdaten stützen die Reddit-Stimmung.")
    elif verdict == "widerspricht":
        s.append("Der Marktabgleich widerspricht jedoch – erhöhtes Hype-Risiko.")
    elif verdict == "relativiert":
        s.append("Der Marktabgleich liefert kein klares Bild.")
    else:
        s.append("Ein Marktabgleich war mangels Kursdaten nicht möglich.")

    advice = {"kaufen": "Insgesamt erscheint eine Kaufposition vertretbar – mit engem Risikomanagement.",
              "verkaufen": "Insgesamt spricht die Lage eher für Zurückhaltung oder Gewinnmitnahmen.",
              "beobachten": "Eine Beobachtungsposition erscheint aktuell sinnvoller als ein aggressiver Einstieg."}[rec]
    s.append(advice)
    return " ".join(s)


# ── v5: Hype Engine ──────────────────────────────────────────────────────────

def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f:
            h = json.load(f)
        h.setdefault("scans", [])
        h.setdefault("recommendations", [])
        return h
    except Exception:
        return {"scans": [], "recommendations": []}


def mention_timeline(history, ticker, days=4):
    """Tages-Timeline: pro Tag der höchste Mentions-Wert (inkl. heute)."""
    by_day = {}
    for scan in history["scans"]:
        day = scan["ts"][:10]
        m = scan.get("tickers", {}).get(ticker, {}).get("mentions", 0)
        by_day[day] = max(by_day.get(day, 0), m)
    ordered = sorted(by_day.items())[-days:]
    return [{"day": d, "mentions": m} for d, m in ordered]


def momentum_score(timeline, n_subs):
    if len(timeline) < 2:
        base = 55  # neu aufgetaucht = per se spannend, aber keine Historie
        growth = None
    else:
        today = timeline[-1]["mentions"]
        prev_avg = max(1.0, sum(t["mentions"] for t in timeline[:-1]) / (len(timeline) - 1))
        growth = round((today - prev_avg) / prev_avg * 100)
        base = 50 + max(-40, min(40, growth / 4))
    base += min(n_subs * 2, 10)
    return int(max(0, min(100, base))), growth


def momentum_label(score):
    if score >= 80: return "🚀 Diskussion wächst extrem schnell"
    if score >= 60: return "📈 Diskussion nimmt deutlich zu"
    if score >= 40: return "➡️ Diskussion stabil"
    return "📉 Diskussion nimmt bereits wieder ab"


def classify_hype(timeline, momentum):
    days_present = sum(1 for t in timeline if t["mentions"] > 0)
    if momentum >= 65 and days_present <= 2:
        return ("hype", "Diskussion ist sehr jung und wächst schnell – "
                        "typisches Muster für kurzfristigen Hype.")
    if days_present >= 3 and momentum >= 40:
        return ("trend", f"Aktie wird seit {days_present} Tagen konstant diskutiert – "
                         "spricht eher für eine nachhaltige Story.")
    if momentum < 40 and days_present >= 2:
        return ("unklar", "Diskussion flacht ab – Momentum ist rückläufig.")
    return ("unklar", "Noch zu wenig Verlaufsdaten für eine klare Einstufung.")


def signal_quality(mentions, delta, sentiment, n_subs, titles):
    score = 0.0
    score += min(mentions, 15)
    score += min(max(delta, 0) * 2, 10)
    score += min(abs(sentiment) * 2, 10)
    score += min(n_subs * 3, 12)
    joined = " ".join(titles)
    memes = (joined.count("🚀") + joined.count("💎") + joined.count("🌕")
             + joined.count("🦍") + joined.count("😱")
             + sum(1 for w in joined.split() if w.isupper() and len(w) > 3 and w.isalpha()))
    score -= min(memes * 1.5, 12)
    pct = int(max(0, min(100, score / 47 * 100)))
    grade = ("A+" if pct >= 85 else "A" if pct >= 70 else
             "B" if pct >= 55 else "C" if pct >= 40 else "D")
    return grade, pct, memes


def reddit_vs_markt(momentum, price):
    reddit_pct = momentum
    if price.get("available"):
        markt_pct = int(max(0, min(100, 50 + price["chg_7d"] * 4)))
    else:
        markt_pct = 50
    if reddit_pct - markt_pct >= 15:
        urteil = "🟢 Reddit erkennt den Trend früher als der Markt"
    elif markt_pct - reddit_pct >= 15:
        urteil = "🔴 Reddit reagiert verspätet – Bewegung ist bereits gelaufen"
    else:
        urteil = "🟡 Reddit und Markt laufen weitgehend synchron"
    return {"reddit": reddit_pct, "markt": markt_pct, "urteil": urteil}


def anstieg_gruende_fallback(themen, news, delta):
    """Gründe aus sauberen Themen – nie rohe Keywords."""
    gruende = []
    if delta > 0:
        gruende.append(f"Mentions +{delta} gegenüber dem letzten Scan")
    for t in themen[:2]:
        gruende.append(f"{t['emoji']} {t['titel']}")
    for n in (news or [])[:2]:
        if n.get("tone") in ("pos", "neg"):
            gruende.append(f"News: {n['title'][:70]}")
    return gruende[:5] or ["Keine eindeutigen Auslöser erkennbar"]


# Fallback-Themen: Keyword-Kategorien -> verständliche Investment-Themen
THEMA_MAP = [
    ({"beat","übertrifft","miss","verfehlt","gewinnwarnung"}, "📊", "Quartalszahlen",
     "Die Community diskutiert die jüngsten bzw. erwarteten Geschäftszahlen."),
    ({"squeeze","short","leerverkauf","puts","calls"}, "🎯", "Optionen & Short-Interest",
     "Diskussion über Optionsaktivität und Short-Positionierungen."),
    ({"überbewertet","bubble","overbought","crash"}, "⚠️", "Bewertungs-Debatte",
     "Ein Teil der Community hält die Aktie nach dem Kursverlauf für zu teuer."),
    ({"undervalued","günstig","oversold","nachkaufen","kaufen","buy","kauf"}, "💰", "Einstiegs-Debatte",
     "Diskussion darüber, ob das aktuelle Kursniveau einen Einstieg rechtfertigt."),
    ({"wachstum","potential","kursziel","upside","uptrend","breakout","ausbruch"}, "📈", "Wachstums-Story",
     "Die Community sieht weiteres Kurspotenzial und diskutiert Kursziele."),
    ({"crash","verlust","bagholder","fällt","drop","schwach"}, "📉", "Kursverluste",
     "Diskussion über die jüngste Kursschwäche und deren Ursachen."),
]


def fallback_themen(bull_hits, bear_hits, mentions):
    """Baut verständliche Themen aus den Keyword-Treffern – nie rohe Tokens."""
    all_hits = Counter(bull_hits + bear_hits)
    total = sum(all_hits.values()) or 1
    themen = []
    for kws, emoji, titel, erklaerung in THEMA_MAP:
        n = sum(c for kw, c in all_hits.items() if kw in kws)
        if n > 0:
            themen.append({
                "emoji": emoji, "titel": titel,
                "anteil_pct": min(100, round(n / total * 100)),
                "beitraege": min(mentions, n),
                "erklaerung": erklaerung,
            })
    themen.sort(key=lambda t: t["anteil_pct"], reverse=True)
    if not themen:
        themen = [{"emoji": "💬", "titel": "Allgemeine Diskussion",
                   "anteil_pct": 100, "beitraege": mentions,
                   "erklaerung": "Kein dominantes Einzelthema erkennbar – breite Diskussion ohne klaren Auslöser."}]
    return themen[:5]


# ── v5: Historie & Performance ───────────────────────────────────────────────

def evaluate_performance(history, current_price_map):
    """Bewertet vergangene Empfehlungen ab 7 Tagen Alter."""
    now = datetime.now(timezone.utc)
    needed = []
    for rec in history["recommendations"]:
        if rec.get("price") and rec["ticker"] not in current_price_map:
            needed.append(rec["ticker"])
    fetched = 0
    for t in dict.fromkeys(needed):
        if fetched >= MAX_HIST_PRICE_FETCH:
            break
        p = quick_price(t)
        time.sleep(0.6)
        fetched += 1
        if p:
            current_price_map[t] = p

    evaluated, stats = [], {"kaufen": [0, 0], "verkaufen": [0, 0], "beobachten": [0, 0]}
    perf_7d, perf_30d = [], []

    for rec in history["recommendations"]:
        ts = rec.get("ts", "")
        try:
            age_days = (now - datetime.fromisoformat(ts)).days
        except Exception:
            continue
        cur = current_price_map.get(rec["ticker"])
        if not rec.get("price") or not cur or age_days < 7:
            continue
        chg = round((cur - rec["price"]) / rec["price"] * 100, 2)
        r = rec["rec"]
        correct = ((r == "kaufen" and chg >= 2) or
                   (r == "verkaufen" and chg <= -2) or
                   (r == "beobachten" and -5 <= chg <= 5))
        stats[r][0] += 1 if correct else 0
        stats[r][1] += 1
        if r == "kaufen":
            if 7 <= age_days < 21:
                perf_7d.append(chg)
            elif age_days >= 21:
                perf_30d.append(chg)
        evaluated.append({**rec, "chg_since": chg, "correct": correct,
                          "age_days": age_days})

    total_ok  = sum(s[0] for s in stats.values())
    total_all = sum(s[1] for s in stats.values())

    def rate(pair):
        return round(pair[0] / pair[1] * 100) if pair[1] else None

    def avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else None

    return evaluated, {
        "hit_rate":        round(total_ok / total_all * 100) if total_all else None,
        "n_evaluated":     total_all,
        "rate_kaufen":     rate(stats["kaufen"]),
        "rate_verkaufen":  rate(stats["verkaufen"]),
        "rate_beobachten": rate(stats["beobachten"]),
        "kauf_perf_7d":    avg(perf_7d),
        "kauf_perf_30d":   avg(perf_30d),
    }


# ── v5: KI über GitHub Models ────────────────────────────────────────────────

def check_ai_status():
    """Prüft beim Start ob GitHub Models erreichbar ist und loggt den Grund bei Fehlern."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("⚠ KI-STATUS: GITHUB_TOKEN fehlt!")
        print("  → In scrape.yml beim Scraper-Step ergänzen:")
        print("      env:")
        print("        GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}")
        return False
    payload = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": "Antworte nur: OK"}],
        "max_tokens": 5,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=payload, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "FinanzAgent/7.1"},
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            json.loads(resp.read().decode())
        print("✓ KI-STATUS: GitHub Models erreichbar – KI-Analysen aktiv")
        return True
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        print(f"⚠ KI-STATUS: HTTP {e.code} – {e.reason}")
        if e.code in (401, 403):
            print("  → Fehlende Berechtigung! In scrape.yml muss stehen:")
            print("      permissions:")
            print("        contents: write")
            print("        models: read")
        elif e.code == 429:
            print("  → Tageslimit von GitHub Models erreicht – ab morgen wieder verfügbar.")
            print("  → Tipp: TOP_N reduzieren oder Cron seltener laufen lassen.")
        if body:
            print(f"  → Antwort: {body}")
        return False
    except Exception as e:
        print(f"⚠ KI-STATUS: {e}")
        return False


def ai_analysis(ticker, name, sentiment, verdict, rec, price, mentions,
                delta, topics, bull_case, bear_case, titles, news,
                momentum, growth, hype_typ):
    """KI-Fazit + Gründe für den Anstieg als JSON. None bei Fehler."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return None

    kurs_info = "Keine Kursdaten."
    if price.get("available"):
        kurs_info = (f"Kurs {price['price']} {price.get('currency','')}, "
                     f"24h {price['chg_1d']:+}%, 7T {price['chg_7d']:+}%, "
                     f"1M {price['chg_1mo']:+}%")
    news_info = "; ".join(n["title"] for n in (news or [])[:3]) or "Keine News."
    growth_info = f"{growth:+}% Mentions-Wachstum vs. Vortage" if growth is not None else "keine Verlaufsdaten"

    prompt = (
        f"Du bist ein nüchterner Finanzanalyst. Analysiere {name or ticker} ({ticker}).\n\n"
        f"Reddit: {mentions} Mentions (Δ {delta:+}), Sentiment {sentiment:+}, "
        f"Momentum {momentum}/100 ({growth_info}), Einstufung: {hype_typ}. "
        f"Bull: {', '.join(bull_case) or 'keine'}. Bear: {', '.join(bear_case) or 'keine'}.\n"
        f"Reddit-Post-Titel:\n" + "\n".join(f"- {t}" for t in (titles or [])[:10]) + "\n"
        f"Markt: {kurs_info}. Verdict: {verdict}. Empfehlung: {rec}.\n"
        f"News: {news_info}\n\n"
        f"Antworte NUR mit validem JSON ohne Markdown:\n"
        f'{{"fazit": "3-4 Sätze Deutsch: 1) Warum Reddit diskutiert, '
        f'2) ob Markt/News das stützen, 3) Einordnung der Empfehlung", '
        f'"gruende": ["3-5 kurze Stichpunkte: wahrscheinlichste Auslöser für die aktuelle Aufmerksamkeit"], '
        f'"themen": [3-5 Objekte. Fasse die Post-Titel zu klar verständlichen Investment-Thesen zusammen. '
        f'VERBOTEN als Thementitel: einzelne generische Wörter wie Buy, Sell, Warning, Hobby, Stock, Aktie. '
        f'Jeder Titel muss eine verständliche These sein (z.B. "AI-Speicherboom", "Bewertungs-Debatte"). Format je Objekt: '
        f'{{"emoji": "passendes Emoji", "titel": "kurzer verständlicher Thementitel (2-5 Wörter)", '
        f'"anteil_pct": geschätzter Anteil an der Diskussion in Prozent (Summe max 100), '
        f'"beitraege": geschätzte Anzahl Posts zu diesem Thema (Summe max {mentions}), '
        f'"erklaerung": "1 Satz Deutsch was die Community dazu diskutiert"}}], '
        f'"analyse": "Ausführliche eigenständige Unternehmensanalyse, 350-500 Wörter Deutsch, '
        f'Fließtext in 4-5 Absätzen (Absätze mit \\n\\n trennen), keine Aufzählungen. Struktur: '
        f'1. Absatz: Geschäftsmodell und Marktposition (Wettbewerber konkret benennen). '
        f'2. Absatz: Wachstumstreiber und Chancen der nächsten 1-2 Jahre. '
        f'3. Absatz: Zentrale Risiken (Wettbewerb, Zyklik, Bewertung, Makro). '
        f'4. Absatz: Einordnung der aktuellen Kurs- und Nachrichtenlage anhand der oben gelieferten Daten. '
        f'5. Absatz: Eigenes Urteil – erscheint die Reddit-Stimmung fundamental gerechtfertigt? '
        f'Gehe dabei explizit auf 1-2 der Reddit-Thesen ein und bestätige oder widerlege sie. '
        f'Nutze für aktuelle Aussagen NUR die gelieferten Markt-/News-Daten, dein Firmenwissen nur für Grundsätzliches. '
        f'Sei konkret und meinungsstark statt generisch."}}'
    )

    payload = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2600,
        "temperature": 0.4,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=payload, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "FinanzAgent/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        text = re.sub(r"^```(json)?|```$", "", text, flags=re.M).strip()
        parsed = json.loads(text)
        if isinstance(parsed.get("fazit"), str) and len(parsed["fazit"]) > 40:
            return parsed
        return None
    except urllib.error.HTTPError as e:
        print(f"    (KI nicht verfügbar: HTTP {e.code} {e.reason})")
        return None
    except Exception as e:
        print(f"    (KI nicht verfügbar: {e})")
        return None


# ── Hauptlogik ───────────────────────────────────────────────────────────────

def run():
    now_iso = datetime.now(timezone.utc).isoformat()
    print(f"\n{'='*50}")
    print(f"Reddit Finanz-Agent v8.1  |  {now_iso[:16]} UTC")
    print(f"{'='*50}")

    check_ai_status()

    history = load_history()
    prev_mentions = {}
    if history["scans"]:
        prev_mentions = {t: d.get("mentions", 0)
                         for t, d in history["scans"][-1].get("tickers", {}).items()}

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
                if len(d["titles"]) < 12:
                    title = p.get("title", "")[:110]
                    if title:
                        d["titles"].append(title)

    # Scan in Historie eintragen (VOR den Timeline-Berechnungen)
    history["scans"].append({
        "ts": now_iso,
        "tickers": {t: {"mentions": d["mentions"],
                        "sentiment": d["bull"] - d["bear"]}
                    for t, d in ticker_data.items() if d["mentions"] >= 2},
    })
    history["scans"] = history["scans"][-250:]

    ranked = sorted(
        [(t, d) for t, d in ticker_data.items() if d["mentions"] >= 2],
        key=lambda x: x[1]["engagement"] + x[1]["mentions"] * 15,
        reverse=True,
    )[:TOP_N]

    print(f"\nLade Kurse & News für Top {len(ranked)} Ticker...")
    recommendations = []
    current_price_map = {}

    for ticker, d in ranked:
        net = d["bull"] - d["bear"]
        reddit_signal = "bullish" if net > 1 else "bearish" if net < -1 else "neutral"

        price = fetch_price_data(ticker)
        time.sleep(1)
        news = fetch_news(ticker) if price.get("available") else []
        time.sleep(1)
        if price.get("available"):
            current_price_map[ticker] = price["price"]

        comparison = build_comparison(net, price)
        rec        = final_recommendation(net, comparison["verdict"])
        delta      = d["mentions"] - prev_mentions.get(ticker, 0)
        conf       = compute_confidence(d["mentions"], net,
                                        comparison["verdict"], price.get("available", False))
        topics     = extract_topics(d["titles"])
        bull_case, bear_case = build_cases(d["bull_hits"], d["bear_hits"])

        # Hype Engine
        timeline          = mention_timeline(history, ticker)
        momentum, growth  = momentum_score(timeline, len(d["sources"]))
        hype_typ, hype_bg = classify_hype(timeline, momentum)
        grade, q_pct, memes = signal_quality(d["mentions"], delta, net,
                                             len(d["sources"]), d["titles"])
        rvm               = reddit_vs_markt(momentum, price)

        # KI-Analyse (Fazit + Gründe)
        ai = ai_analysis(ticker, price.get("name", ticker), net,
                         comparison["verdict"], rec, price, d["mentions"],
                         delta, topics, bull_case, bear_case, d["titles"],
                         news, momentum, growth, hype_typ)
        if ai:
            fazit, gruende, fazit_quelle = ai["fazit"], ai.get("gruende", []), "KI (GitHub Models)"
            themen = ai.get("themen", [])
            GENERIC = {"buy","sell","warning","hobby","stock","aktie","stocks",
                       "kaufen","verkaufen","news","reddit","diskussion"}
            themen = [t for t in themen
                      if isinstance(t, dict) and len(str(t.get("titel", ""))) > 7
                      and str(t.get("titel", "")).strip().lower() not in GENERIC
                      and t.get("erklaerung")][:5]
            if not themen:
                themen = fallback_themen(d["bull_hits"], d["bear_hits"], d["mentions"])
            analyse = str(ai.get("analyse", "")).strip()
            if len(analyse) < 100:
                analyse = ""
        else:
            fazit = build_fazit(ticker, price.get("name", ticker), net,
                                comparison["verdict"], rec, price, d["mentions"], delta)
            themen = fallback_themen(d["bull_hits"], d["bear_hits"], d["mentions"])
            gruende = anstieg_gruende_fallback(themen, news, delta)
            analyse = ""
            fazit_quelle = "regelbasiert"

        # Empfehlung in Historie
        history["recommendations"].append({
            "ts": now_iso, "ticker": ticker, "rec": rec,
            "confidence": conf, "engagement": round(d["engagement"]),
            "price": price.get("price"),
        })

        # Verlauf dieses Tickers für die Karte
        verlauf = [r for r in history["recommendations"]
                   if r["ticker"] == ticker][-6:]

        print(f"  {'✓' if price.get('available') else '○'} {ticker}: "
              f"{rec} · Momentum {momentum} · {grade} · {hype_typ}")

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
            "themen":         themen,
            "bull_case":      bull_case,
            "bear_case":      bear_case,
            "price":          price,
            "news":           news,
            "comparison":     comparison,
            "fazit":          fazit,
            "fazit_quelle":   fazit_quelle,
            "analyse":        analyse,
            "gruende":        gruende,
            "momentum":       momentum,
            "momentum_label": momentum_label(momentum),
            "growth_pct":     growth,
            "timeline":       timeline,
            "hype_typ":       hype_typ,
            "hype_begruendung": hype_bg,
            "quality_grade":  grade,
            "quality_pct":    q_pct,
            "reddit_vs_markt": rvm,
            "verlauf":        verlauf,
        })

    history["recommendations"] = history["recommendations"][-600:]

    # Historische Performance auswerten
    print("\nWerte historische Empfehlungen aus...")
    evaluated, stats = evaluate_performance(history, current_price_map)
    if stats["n_evaluated"]:
        print(f"  ✓ {stats['n_evaluated']} Empfehlungen ausgewertet, "
              f"Trefferquote {stats['hit_rate']}%")
    else:
        print("  ○ Noch keine auswertbaren Empfehlungen (mind. 7 Tage Historie nötig)")

    output = {
        "generated_at":    now_iso,
        "total_posts":     total_posts,
        "unique_tickers":  len(ticker_data),
        "subreddits":      sub_results,
        "recommendations": recommendations,
        "stats":           stats,
        "history_evaluated": evaluated[-40:],
    }

    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    with open(HISTORY, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False)

    print(f"\n{'='*50}")
    print(f"✓ {len(recommendations)} Empfehlungen → {OUTPUT}")
    print(f"✓ Historie: {len(history['scans'])} Scans, "
          f"{len(history['recommendations'])} Empfehlungen → {HISTORY}")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    run()

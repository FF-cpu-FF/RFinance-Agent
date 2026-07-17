"""
Reddit Finanz-Agent v15 – scraper.py
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
TOP_N   = 6
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

# Squeeze-/Meme-Wave-Vokabular für das Opportunity-Radar
SQUEEZE_KW = ["squeeze","short interest","gamma","float","ftd","moass",
    "diamond hands","💎","🙌","🦍","hedgies","shortseller","leerverkäufer",
    "short quote","yolo","all in","to the moon","naked short","shorts are",
    "heavily shorted","stark geshortet","shortquote"]

# Firmennamen -> Ticker für den Trump-Tracker
COMPANY_MAP = {
    "tesla": "TSLA", "apple": "AAPL", "amazon": "AMZN", "boeing": "BA",
    "pfizer": "PFE", "intel": "INTC", "nvidia": "NVDA", "micron": "MU",
    "general motors": "GM", "ford": "F", "meta": "META", "facebook": "META",
    "google": "GOOGL", "alphabet": "GOOGL", "microsoft": "MSFT",
    "exxon": "XOM", "chevron": "CVX", "lockheed": "LMT", "raytheon": "RTX",
    "us steel": "X", "nippon steel": "NPSCY", "harley": "HOG",
    "john deere": "DE", "goldman": "GS", "jpmorgan": "JPM", "jp morgan": "JPM",
    "bank of america": "BAC", "disney": "DIS", "comcast": "CMCSA",
    "paramount": "PARA", "coca-cola": "KO", "coca cola": "KO",
    "mcdonald": "MCD", "walmart": "WMT", "target": "TGT", "netflix": "NFLX",
    "at&t": "T", "verizon": "VZ", "tsmc": "TSM", "softbank": "SFTBY",
    "caterpillar": "CAT", "carrier": "CARR", "truth social": "DJT",
    "trump media": "DJT", "$djt": "DJT", "palantir": "PLTR", "oracle": "ORCL",
}

# Marktrelevante Politik-Themen (bewegen Märkte auch ohne Firmennennung)
POLICY_KW = {
    "tariff": "🏛️ Zölle", "tariffs": "🏛️ Zölle", "zoll": "🏛️ Zölle",
    "trade deal": "🏛️ Handelsdeal", "trade agreement": "🏛️ Handelsdeal",
    "sanction": "🏛️ Sanktionen", "federal reserve": "🏛️ Fed",
    "interest rate": "🏛️ Zinsen", "jerome powell": "🏛️ Fed",
    "tax cut": "🏛️ Steuern", "taxes": "🏛️ Steuern",
    "chips act": "🏛️ Chips Act", "export control": "🏛️ Exportkontrollen",
    "oil price": "🏛️ Öl", "opec": "🏛️ Öl", "drill": "🏛️ Energie",
    "data center": "🏛️ Rechenzentren", "crypto": "🏛️ Krypto",
    "bitcoin": "🏛️ Krypto", "pharma prices": "🏛️ Pharma",
    "drug prices": "🏛️ Pharma", "auto industry": "🏛️ Autoindustrie",
}


def detect_policy(text):
    t = text.lower()
    hits = []
    for kw, label in POLICY_KW.items():
        if kw in t and label not in hits:
            hits.append(label)
    return hits[:3]


EVENT_KW = ["beat","beats","fda","approval","approved","acquisition","acquire",
    "merger","upgrade","downgrade","contract","partnership","guidance","launch",
    "buyout","takeover","stake","wins","order","deal","invests","split",
    "spinoff","recall","lawsuit","probe","insider","raises","surges","soars",
    "plunges","earnings"]


def gh_chat(prompt, max_tokens=1000):
    """Generischer GitHub-Models-Aufruf. Gibt Text oder None zurück."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return None
    payload = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.4,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(
            "https://models.github.ai/inference/chat/completions",
            data=payload, method="POST",
            headers={"Authorization": f"Bearer {token}",
                     "Content-Type": "application/json",
                     "User-Agent": "FinanzAgent/13.0"})
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode())
        text = data["choices"][0]["message"]["content"].strip()
        return re.sub(r"^```(json)?|```$", "", text, flags=re.M).strip()
    except Exception as e:
        print(f"    (KI-Aufruf fehlgeschlagen: {e})")
        return None


# ── 🔥 Spannende Aktien des Tages ────────────────────────────────────────────

def fetch_trending(max_n=10):
    """Yahoo Trending-Ticker (US) als Kandidaten-Universum."""
    url = "https://query1.finance.yahoo.com/v1/finance/trending/US?count=20"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        quotes = data["finance"]["result"][0].get("quotes", [])
        symbols = [q.get("symbol", "") for q in quotes]
        clean = [s for s in symbols
                 if s and s.isalpha() and 1 < len(s) <= 5 and s not in SKIP]
        return clean[:max_n]
    except Exception as e:
        print(f"  ✗ Trending-Liste: {e}")
        return []


def build_spannende_aktien():
    """Story-getriebene Bewegungen statt langweiliger Top-Gainer-Liste."""
    candidates = []
    for sym in fetch_trending(10):
        vol = volume_profile(sym)
        time.sleep(0.6)
        if not vol:
            continue
        news = fetch_news(sym, 3)
        time.sleep(0.5)
        has_event = any(
            any(k in (n["title"] or "").lower() for k in EVENT_KW)
            for n in news)
        chg = vol.get("chg_1d") or 0
        vr  = vol.get("vol_ratio") or 0
        # Filter: nur mit Story-Kriterium
        if abs(chg) >= 8 or vr >= 2 or has_event:
            candidates.append({
                "ticker": sym, "name": vol.get("name", sym),
                "price": vol.get("price"), "currency": vol.get("currency", "USD"),
                "chg_1d": chg, "vol_ratio": vr, "has_event": has_event,
                "news": news,
                "_score": abs(chg) + vr * 3 + (5 if has_event else 0),
            })
    candidates.sort(key=lambda x: x["_score"], reverse=True)
    picks = candidates[:5]
    if not picks:
        return []

    # KI-Einordnung (1 Batch-Aufruf für alle)
    lines = []
    for p in picks:
        heads = "; ".join(n["title"] for n in p["news"][:3]) or "keine Headlines"
        lines.append(f"- {p['ticker']} ({p['name']}): {p['chg_1d']:+}% heute, "
                     f"Volumen {p['vol_ratio']}x. News: {heads}")
    prompt = (
        "Du bist ein nüchterner Finanzanalyst. Für jede Aktie unten, "
        "basierend NUR auf den gelieferten Daten und Headlines:\n"
        + "\n".join(lines) +
        "\n\nAntworte NUR mit validem JSON-Array ohne Markdown, je Aktie ein Objekt:\n"
        '[{"ticker": "...", '
        '"warum": ["2-4 kurze Stichpunkte Deutsch: was treibt die Aktie heute (aus den Headlines abgeleitet)"], '
        '"bedeutung": "1 Satz: einmaliges Ereignis oder langfristiger Treiber?", '
        '"sterne": 1 bis 3 (1=kurzfristiger Momentum-Trade, 2=Watchlist, 3=langfristig interessant), '
        '"risiken": ["2-3 kurze konkrete Risiken"]}]'
    )
    parsed = None
    text = gh_chat(prompt, 1100)
    if text:
        try:
            parsed = {x.get("ticker"): x for x in json.loads(text) if isinstance(x, dict)}
        except Exception:
            parsed = None

    out = []
    for p in picks:
        ai = (parsed or {}).get(p["ticker"], {})
        warum = ai.get("warum") or [
            n["title"][:80] for n in p["news"][:2] if n.get("title")
        ] or ["Ungewöhnliche Kurs-/Volumenbewegung"]

        # Regelbasierte Einordnung als Fallback
        if ai.get("bedeutung"):
            bedeutung = ai["bedeutung"]
        else:
            chg = abs(p["chg_1d"])
            vr = p["vol_ratio"] or 0
            if p["has_event"] and chg >= 8:
                bedeutung = "Starke Kursbewegung mit konkretem Nachrichtenkatalysator – potenziell nachhaltiger Treiber."
            elif p["has_event"]:
                bedeutung = "Konkretes Unternehmensereignis – Nachhaltigkeit hängt von den Details ab."
            elif chg >= 12:
                bedeutung = f"Extreme Bewegung ({p['chg_1d']:+}%) ohne klare Headlines – erhöhtes Risiko eines kurzfristigen Überschießens."
            elif vr >= 3:
                bedeutung = f"Handelsvolumen {vr}× über Normal – institutionelle Aktivität möglich, Ursache prüfen."
            else:
                bedeutung = "Auffällige Bewegung – ob kurzfristiger Impuls oder Trendwende, bleibt abzuwarten."

        # Regelbasierte Sterne als Fallback
        if ai.get("sterne"):
            sterne = min(3, max(1, int(ai["sterne"])))
        else:
            sterne = 3 if (p["has_event"] and abs(p["chg_1d"]) >= 5) else 2 if p["has_event"] else 1

        # Regelbasierte Risiken als Fallback
        risiken = ai.get("risiken") or []
        if not risiken:
            risiken = ["Hohe Volatilität nach starker Bewegung – Rücksetzer wahrscheinlich"]
            if p["chg_1d"] > 8:
                risiken.append("Kurs bereits stark gestiegen – ungünstiger Einstiegszeitpunkt möglich")
            elif p["chg_1d"] < -8:
                risiken.append("Fallender Kurs könnte weiteren Abwärtsdruck signalisieren")
            if (p["vol_ratio"] or 0) >= 2:
                risiken.append("Ungewöhnlich hohes Volumen kann auch auf Panikverkäufe hindeuten")

        out.append({
            "ticker": p["ticker"], "name": p["name"],
            "price": p["price"], "currency": p["currency"],
            "chg_1d": p["chg_1d"], "vol_ratio": p["vol_ratio"],
            "warum": warum[:4],
            "bedeutung": bedeutung,
            "sterne": sterne,
            "risiken": risiken[:3],
            "news": p["news"][:2],
        })
    return out


# ── 🤝 M&A Deal-Tracker ──────────────────────────────────────────────────────

MA_KW = ["acquir", "merger", "takeover", "buyout", "to buy ", "übern", "buys ",
         "agrees to buy", "all-cash", "all-stock"]
MA_BLOCK = ["denies", "rules out", "not for sale", "rumor debunked"]


def _parse_rss_items(content, source_label, max_n):
    """Generischer RSS-Item-Parser (Google News & FT nutzen <item>)."""
    items = []
    try:
        root = ET.fromstring(content)
        for item in root.iter("item"):
            title = (item.findtext("title", "") or "").strip()
            if title:
                items.append({
                    "title": title[:160],
                    "link":  item.findtext("link", "") or "",
                    "date":  (item.findtext("pubDate", "") or "")[:16],
                    "source": source_label,
                })
            if len(items) >= max_n:
                break
    except Exception:
        pass
    return items


def fetch_ma_headlines(max_n=6):
    """M&A-Headlines aus mehreren Quellen: FT (Companies + Markets) + Google News."""
    feeds = [
        ("https://www.ft.com/companies?format=rss", "FT"),
        ("https://www.ft.com/markets?format=rss",   "FT"),
        (("https://news.google.com/rss/search?"
          "q=(acquisition%20OR%20merger%20OR%20takeover)%20billion"
          "&hl=en-US&gl=US&ceid=US:en"), "Google News"),
    ]
    collected = []
    for url, label in feeds:
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as resp:
                content = resp.read().decode("utf-8", errors="replace")
            collected += _parse_rss_items(content, label, 20)
            time.sleep(1)
        except Exception as e:
            print(f"  ✗ {label}-Feed: {e}")

    # Nur M&A-relevante Headlines, Dementis raus, deduplizieren
    items, seen = [], set()
    # FT zuerst sortieren (Qualitätsquelle bevorzugen)
    collected.sort(key=lambda x: 0 if x["source"] == "FT" else 1)
    for it in collected:
        tl = it["title"].lower()
        if not any(k in tl for k in MA_KW):
            continue
        if any(b in tl for b in MA_BLOCK):
            continue
        key = tl[:40]
        if key in seen:
            continue
        seen.add(key)
        items.append(it)
        if len(items) >= max_n:
            break
    src_counts = {}
    for it in items:
        src_counts[it["source"]] = src_counts.get(it["source"], 0) + 1
    if items:
        print(f"  ✓ M&A-Headlines: {', '.join(f'{v}× {k}' for k, v in src_counts.items())}")
    return items


def build_ma_tracker():
    heads = fetch_ma_headlines(5)
    if not heads:
        return []
    prompt = (
        "Du bist ein M&A-Analyst. Analysiere diese aktuellen Deal-Headlines. "
        "Nutze NUR Informationen aus den Headlines selbst – wenn Dealgröße, "
        "Prämie oder Zahlungsart nicht genannt sind, schreibe exakt 'k.A.'. "
        "Dein Branchen-/Firmenwissen darfst du nur für die strategische "
        "Einordnung nutzen, nicht für Zahlen.\n\nHeadlines:\n"
        + "\n".join(f"{i+1}. {h['title']}" for i, h in enumerate(heads)) +
        "\n\nAntworte NUR mit validem JSON-Array ohne Markdown, je Deal ein Objekt "
        "(nur Headlines mit klar erkennbarem Käufer UND Ziel aufnehmen):\n"
        '[{"headline_nr": 1, "kaeufer": "...", "ziel": "...", "groesse": "... oder k.A.", '
        '"branche": "...", "warum": ["2-3 strategische Motive"], '
        '"synergien": ["1-2 mögliche Synergien"], '
        '"risiken": ["2-3 Risiken, z.B. Kartellrecht, Integrationsrisiko"], '
        '"einordnung": "strategisch sinnvoll ✅ | teuer ⚠️ | defensiver Deal | Wachstumsdeal | Konsolidierung"}]'
    )
    parsed = []
    text = gh_chat(prompt, 1300)
    if text:
        try:
            parsed = [x for x in json.loads(text) if isinstance(x, dict)]
        except Exception:
            parsed = []

    out = []
    if parsed:
        for deal in parsed[:4]:
            nr = deal.get("headline_nr")
            src = heads[nr - 1] if isinstance(nr, int) and 1 <= nr <= len(heads) else {}
            out.append({
                "kaeufer":    str(deal.get("kaeufer", "k.A."))[:60],
                "ziel":       str(deal.get("ziel", "k.A."))[:60],
                "groesse":    str(deal.get("groesse", "k.A."))[:40],
                "branche":    str(deal.get("branche", ""))[:40],
                "warum":      (deal.get("warum") or [])[:3],
                "synergien":  (deal.get("synergien") or [])[:2],
                "risiken":    (deal.get("risiken") or [])[:3],
                "einordnung": str(deal.get("einordnung", ""))[:60],
                "link":       src.get("link", ""),
                "date":       src.get("date", ""),
                "headline":   src.get("title", ""),
                "source":     src.get("source", ""),
            })
    else:
        # Fallback ohne KI: nur Headlines listen
        for h in heads[:4]:
            out.append({"kaeufer": "", "ziel": "", "groesse": "k.A.", "branche": "",
                        "warum": [], "synergien": [], "risiken": [],
                        "einordnung": "", "link": h["link"],
                        "date": h["date"], "headline": h["title"],
                        "source": h.get("source", "")})
    return out


# ── Trump Truth-Social-Tracker ───────────────────────────────────────────────

def analyze_trump_post(text):
    """Findet erwähnte Firmen/Ticker in einem Post."""
    found = []
    t = text.lower()
    for name, ticker in COMPANY_MAP.items():
        if name in t:
            found.append({"name": name.title(), "ticker": ticker})
    for m in re.finditer(r'\$([A-Z]{1,5})\b', text):
        tk = m.group(1)
        if tk not in [f["ticker"] for f in found] and tk not in SKIP:
            found.append({"name": tk, "ticker": tk})
    # Duplikate über Ticker entfernen
    seen, unique = set(), []
    for f in found:
        if f["ticker"] not in seen:
            seen.add(f["ticker"])
            unique.append(f)
    return unique


def fetch_trump_posts(max_posts=10):
    """Neueste Trump-Posts via trumpstruth.org RSS, Fallback CNN-Archiv."""
    # Primär: RSS
    try:
        req = urllib.request.Request("https://www.trumpstruth.org/feed", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        root = ET.fromstring(content)
        posts = []
        for item in root.iter("item"):
            # Versuche mehrere Felder — Truth Social RSS ist inkonsistent
            desc = item.findtext("description", "") or ""
            title = item.findtext("title", "") or ""
            encoded = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded", "") or ""
            raw = desc or encoded or title
            text = re.sub(r"<[^>]+>", " ", raw).strip()
            text = re.sub(r"\s+", " ", text)
            link = item.findtext("link", "") or ""
            # Bei leeren Posts mit Link: Link als Inhalt anzeigen
            if not text and link:
                text = f"[Link geteilt] {link}"
            # Komplett leere Posts überspringen
            if not text or len(text) < 5:
                continue
            posts.append({
                "text": text[:400],
                "url":  link,
                "date": (item.findtext("pubDate", "") or "")[:22],
                "id":   item.findtext("guid", "") or link or text[:40],
            })
            if len(posts) >= max_posts:
                break
        if posts:
            print(f"  ✓ Trump-Tracker: {len(posts)} Posts (trumpstruth.org)")
            return posts
    except Exception as e:
        print(f"  ✗ trumpstruth.org: {e}")

    # Fallback: CNN-Archiv (groß, daher nur bei Bedarf)
    try:
        req = urllib.request.Request(
            "https://ix.cnn.io/data/truth-social/truth_archive.json", headers=UA)
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        data = sorted(data, key=lambda p: p.get("created_at", ""), reverse=True)[:max_posts]
        posts = []
        for p in data:
            text = re.sub(r"<[^>]+>", " ", p.get("content", "") or "").strip()
            text = re.sub(r"\s+", " ", text)
            if not text or len(text) < 5:
                continue
            posts.append({
                "text": text[:400],
                "url":  p.get("url", ""),
                "date": (p.get("created_at", "") or "")[:16].replace("T", " "),
                "id":   str(p.get("id", "")),
            })
        if posts:
            print(f"  ✓ Trump-Tracker: {len(posts)} Posts (CNN-Archiv)")
        return posts
    except Exception as e:
        print(f"  ✗ CNN-Archiv: {e}")
        return []


def fetch_whitehouse_items(max_n=5):
    """Offizielle Statements/Reden/Pressebriefings vom Weißen Haus (RSS)."""
    try:
        req = urllib.request.Request("https://www.whitehouse.gov/feed/", headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        items = _parse_rss_items(content, "Weißes Haus", max_n)
        for it in items:
            it["text"] = it.pop("title")
            it["url"]  = it.pop("link")
            it["id"]   = it["url"]
        if items:
            print(f"  ✓ Weißes Haus: {len(items)} Meldungen")
        return items
    except Exception as e:
        print(f"  ✗ Weißes Haus: {e}")
        return []


def fetch_trump_news(max_n=8):
    """Google News: fängt marktrelevante Trump-Äußerungen aus X, Pressekonferenzen etc. ein."""
    url = ("https://news.google.com/rss/search?q=%22Trump%22"
           "&hl=en-US&gl=US&ceid=US:en")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        items = _parse_rss_items(content, "News (X/Presse)", 25)
        out = []
        for it in items:
            it["text"] = it.pop("title")
            it["url"]  = it.pop("link")
            it["id"]   = it["url"]
            out.append(it)
            if len(out) >= max_n:
                break
        return out
    except Exception as e:
        print(f"  ✗ Trump-News: {e}")
        return []


def build_trump_tracker(history):
    """Truth Social + Weißes Haus + News. Erkennt Firmen- UND Politik-Relevanz."""
    posts = fetch_trump_posts(8)
    for p in posts:
        p["source"] = "Truth Social"
    wh = fetch_whitehouse_items(5)
    news = fetch_trump_news(10)

    seen = set(history.get("trump_seen", []))
    market_hits = 0
    out = []

    for p in posts + wh + news:
        companies = analyze_trump_post(p.get("text", ""))
        policy = detect_policy(p.get("text", ""))
        relevant = bool(companies or policy)
        # News-Quellen nur aufnehmen wenn marktrelevant (sonst Politik-Rauschen)
        if p.get("source") in ("News (X/Presse)", "Weißes Haus") and not relevant:
            continue
        if relevant:
            market_hits += 1
        out.append({
            "text": p.get("text", "")[:400],
            "url": p.get("url", ""),
            "date": p.get("date", ""),
            "source": p.get("source", ""),
            "companies": companies,
            "policy": policy,
            "is_new": p.get("id", "") not in seen,
        })

    all_ids = [p.get("id", "") for p in posts + wh + news if p.get("id")]
    history["trump_seen"] = (list(seen) + all_ids)[-400:]
    return {"posts": out[:14], "market_hits": market_hits}

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
                link_el = entry.find("atom:link", ns)
                url = link_el.get("href", "") if link_el is not None else ""
                posts.append({"title": title, "selftext": body, "url": url})
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

def yahoo_chart(ticker, rng, interval, with_volume=False):
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?range={rng}&interval={interval}")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode())
        result = data["chart"]["result"][0]
        ts     = result.get("timestamp", [])
        quote  = result["indicators"]["quote"][0]
        closes = quote.get("close", [])
        vols   = quote.get("volume", []) if with_volume else []
        series = [{"t": t, "c": round(c, 2)} for t, c in zip(ts, closes) if c is not None]
        volumes = [v for v in vols if v] if with_volume else []
        if with_volume:
            return series, result.get("meta", {}), volumes
        return series, result.get("meta", {})
    except Exception:
        if with_volume:
            return [], {}, []
        return [], {}


def volume_profile(ticker):
    """Aktueller Kurs + Volumen-Ratio (heute vs. 20-Tage-Schnitt). Für Squeeze-Radar."""
    series, meta, vols = yahoo_chart(ticker, "1mo", "1d", with_volume=True)
    if not series or len(vols) < 5:
        return None
    today_vol = vols[-1]
    avg_vol = sum(vols[:-1]) / len(vols[:-1])
    return {
        "price": series[-1]["c"],
        "currency": meta.get("currency", "USD"),
        "name": meta.get("longName") or meta.get("shortName") or ticker,
        "vol_ratio": round(today_vol / avg_vol, 1) if avg_vol else None,
        "chg_1d": round((series[-1]["c"] - series[-2]["c"]) / series[-2]["c"] * 100, 2)
                  if len(series) >= 2 else 0.0,
    }


def squeeze_score(d, delta, is_new, memes, vol):
    """0-100: Wie sehr ähnelt das Muster einem frühen Squeeze/Meme-Wave-Setup?"""
    signals = []
    score = 0

    kw = d.get("squeeze_hits", 0)
    if kw:
        pts = min(kw * 8, 30)
        score += pts
        signals.append(f"Squeeze-Vokabular in Posts ({kw}× erkannt)")

    if delta >= 3:
        pts = min(delta * 4, 20)
        score += pts
        signals.append(f"Mention-Spike: +{delta} vs. letzter Scan")

    if is_new:
        score += 15
        signals.append("Ticker neu in der Diskussion aufgetaucht")

    if memes >= 3:
        score += min(memes * 2, 10)
        signals.append("Hohe Meme-Intensität (🚀💎🦍)")

    if vol and vol.get("vol_ratio"):
        vr = vol["vol_ratio"]
        if vr >= 3:
            score += 20
            signals.append(f"Handelsvolumen {vr}× über Normal – ungewöhnliche Aktivität")
        elif vr >= 2:
            score += 12
            signals.append(f"Handelsvolumen {vr}× über Normal")
        elif vr >= 1.5:
            score += 6
            signals.append(f"Erhöhtes Handelsvolumen ({vr}×)")

    if vol and vol.get("price") and vol["price"] < 25:
        score += 5
        signals.append("Niedriger Kurs – typisch für Retail-Wellen")

    return min(100, score), signals


def build_squeeze_radar(ticker_data, prev_mentions, history):
    """Findet die Top-Kandidaten für ein mögliches Squeeze-/Meme-Wave-Setup."""
    known_tickers = set()
    for scan in history["scans"][:-1]:
        known_tickers.update(scan.get("tickers", {}).keys())

    candidates = []
    for t, d in ticker_data.items():
        if d["mentions"] < 2:
            continue
        delta = d["mentions"] - prev_mentions.get(t, 0)
        is_new = t not in known_tickers
        joined = " ".join(d["titles"])
        memes = (joined.count("🚀") + joined.count("💎") + joined.count("🦍"))
        # Vor-Score ohne Volumen zum Vorsortieren
        pre, _ = squeeze_score(d, delta, is_new, memes, None)
        if pre >= 15:
            candidates.append((pre, t, d, delta, is_new, memes))

    candidates.sort(reverse=True)
    radar = []
    for pre, t, d, delta, is_new, memes in candidates[:6]:
        vol = volume_profile(t)
        time.sleep(0.7)
        score, signals = squeeze_score(d, delta, is_new, memes, vol)
        if score >= 35:
            radar.append({
                "ticker": t,
                "name": (vol or {}).get("name", t),
                "score": score,
                "signals": signals,
                "mentions": d["mentions"],
                "delta": delta,
                "vol_ratio": (vol or {}).get("vol_ratio"),
                "price": (vol or {}).get("price"),
                "currency": (vol or {}).get("currency", "USD"),
                "chg_1d": (vol or {}).get("chg_1d"),
                "sources": d["sources"],
            })
    radar.sort(key=lambda x: x["score"], reverse=True)
    return radar[:5]


def fetch_price_data(ticker):
    out = {"available": False}
    series_1mo, meta = yahoo_chart(ticker, "1mo", "1d")
    if not series_1mo:
        return out
    time.sleep(0.5)
    series_1d, _ = yahoo_chart(ticker, "1d", "15m")
    time.sleep(0.5)
    series_5d, _ = yahoo_chart(ticker, "5d", "60m")
    time.sleep(0.5)
    series_1y, _ = yahoo_chart(ticker, "1y", "1wk")

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
        "chart_1y":  series_1y[-56:],
        "chg_1d":    pct(price, series_1d[0]["c"]) if series_1d else 0.0,
        "chg_7d":    pct(price, closes[-6]) if len(closes) >= 6 else 0.0,
        "chg_1mo":   pct(price, closes[0]) if len(closes) >= 2 else 0.0,
        "chg_1y":    pct(price, series_1y[0]["c"]) if series_1y else None,
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
        f"Reddit-Post-Titel (nummeriert):\n"
        + "\n".join(f"{i+1}. {t}" for i, t in enumerate((titles or [])[:10])) + "\n"
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
        f'"posts": [Nummern der zugehörigen Post-Titel aus der nummerierten Liste, max 3], '
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
        f'Markiere 4-6 zentrale Kernaussagen mit **doppelten Sternchen** (Beispiel: **HBM-Nachfrage bleibt der Haupttreiber**). '
        f'Sei konkret und meinungsstark statt generisch.", '
        f'"konkurrenten": [2-4 Objekte: die wichtigsten Wettbewerber. Format: '
        f'{{"name": "Firmenname", "ticker": "Ticker oder k.A.", '
        f'"vergleich": "1 kurzer Satz: Stellung im Vergleich zu {ticker} (Marktanteil, Stärke, Schwäche)"}}]}}'
    )

    payload = json.dumps({
        "model": "openai/gpt-4o-mini",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2900,
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
    print(f"Reddit Finanz-Agent v15   |  {now_iso[:16]} UTC")
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
        "squeeze_hits": 0, "post_refs": [],
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
            sq_hits   = len(matched_keywords(text.lower(), SQUEEZE_KW))
            for ticker in tickers:
                d = ticker_data[ticker]
                d["bull"]        += len(bull_hits)
                d["bear"]        += len(bear_hits)
                d["mentions"]    += 1
                d["engagement"]  += len(bull_hits) + len(bear_hits) + 1
                d["bull_hits"]   += bull_hits
                d["bear_hits"]   += bear_hits
                d["squeeze_hits"] += sq_hits
                if sub not in d["sources"]:
                    d["sources"].append(sub)
                if len(d["titles"]) < 12:
                    title = p.get("title", "")[:110]
                    if title:
                        d["titles"].append(title)
                        d["post_refs"].append({"title": title,
                                               "url": p.get("url", "")})

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
            # Post-Indizes der KI in echte Links übersetzen
            refs = d["post_refs"]
            for th in themen:
                idxs = th.pop("posts", []) or []
                links = []
                for i in idxs:
                    try:
                        i = int(i)
                        if 1 <= i <= len(refs) and refs[i-1].get("url"):
                            links.append(refs[i-1])
                    except (ValueError, TypeError):
                        pass
                th["links"] = links[:3]
            if not themen:
                themen = fallback_themen(d["bull_hits"], d["bear_hits"], d["mentions"])
            analyse = str(ai.get("analyse", "")).strip()
            if len(analyse) < 100:
                analyse = ""
            konkurrenten = [k for k in (ai.get("konkurrenten") or [])
                            if isinstance(k, dict) and k.get("name")
                            and k.get("vergleich")][:4]
        else:
            fazit = build_fazit(ticker, price.get("name", ticker), net,
                                comparison["verdict"], rec, price, d["mentions"], delta)
            themen = fallback_themen(d["bull_hits"], d["bear_hits"], d["mentions"])
            gruende = anstieg_gruende_fallback(themen, news, delta)
            analyse = ""
            konkurrenten = []
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
            "top_posts":      d["post_refs"][:5],
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
            "konkurrenten":   konkurrenten,
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

    # Squeeze-/Opportunity-Radar
    print("\nScanne nach Squeeze-/Meme-Wave-Mustern...")
    radar = build_squeeze_radar(ticker_data, prev_mentions, history)
    if radar:
        for r in radar:
            print(f"  🎯 {r['ticker']}: Score {r['score']} – {len(r['signals'])} Signale")
    else:
        print("  ○ Keine auffälligen Muster in diesem Scan")

    # Trump Truth-Social-Tracker
    print("\nLade Trump-Posts (Truth Social)...")
    trump = build_trump_tracker(history)
    if trump["market_hits"]:
        print(f"  🦅 {trump['market_hits']} Post(s) mit Firmen-Erwähnungen!")

    # 🔥 Spannende Aktien des Tages
    print("\nSuche spannende Story-Aktien (Trending + Filter)...")
    spannende = build_spannende_aktien()
    print(f"  🔥 {len(spannende)} Aktien mit Story gefunden")

    # 🤝 M&A Deal-Tracker
    print("\nLade M&A-Deals...")
    ma_deals = build_ma_tracker()
    print(f"  🤝 {len(ma_deals)} Deals analysiert")

    output = {
        "generated_at":    now_iso,
        "total_posts":     total_posts,
        "unique_tickers":  len(ticker_data),
        "subreddits":      sub_results,
        "recommendations": recommendations,
        "stats":           stats,
        "history_evaluated": evaluated[-40:],
        "squeeze_radar":   radar,
        "trump_tracker":   trump,
        "spannende_aktien": spannende,
        "ma_deals":        ma_deals,
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

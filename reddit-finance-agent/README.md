# Reddit Finanz-Agent 🤖📈

Stündlicher Sentiment-Scraper für r/Mauerstrassenwetten, r/wallstreetbets und r/Ameisenstrassenwetten.  
Läuft komplett kostenlos via **GitHub Actions** + **GitHub Pages** – kein Server nötig.

---

## Setup (5 Minuten)

### 1. Repo erstellen
- Neues **öffentliches** GitHub-Repo anlegen (z.B. `reddit-finanz-agent`)
- Alle Dateien aus diesem Zip hochladen

### 2. GitHub Pages aktivieren
- Repo → **Settings** → **Pages**
- Source: `Deploy from a branch`
- Branch: `main` / Ordner: `/docs`
- Speichern → nach ~1 Min erreichbar unter `https://<dein-username>.github.io/<repo-name>/`

### 3. Actions-Permissions prüfen
- Repo → **Settings** → **Actions** → **General**
- Workflow permissions: **Read and write permissions** aktivieren
- Speichern

### 4. Ersten Lauf starten
- Repo → **Actions** → **Reddit Finanz-Agent** → **Run workflow**
- Nach ~30 Sekunden erscheint `docs/data.json` im Repo
- Dein Dashboard unter der GitHub-Pages-URL zeigt die Ergebnisse

---

## Dateistruktur

```
reddit-finanz-agent/
├── scraper.py                    # Haupt-Script (nur Python stdlib)
├── .github/
│   └── workflows/
│       └── scrape.yml            # Stündlicher Cron-Job
└── docs/
    ├── index.html                # Dashboard (GitHub Pages)
    └── data.json                 # Wird automatisch befüllt ← nicht manuell bearbeiten
```

---

## Anpassen

**Andere Subreddits** → `scraper.py`, Zeile `SUBREDDITS = [...]`

**Scan-Häufigkeit** → `scrape.yml`, Zeile `cron: "0 * * * *"`  
Beispiele:
- `"0 * * * *"` → stündlich
- `"0 8,12,18 * * *"` → 3× täglich (8h, 12h, 18h UTC)
- `"*/30 * * * *"` → alle 30 Minuten

**Mehr Posts** → `scraper.py`, Zeile `LIMIT = 50` → z.B. `100`

---

## Hinweis

⚠️ Keine Anlageberatung. Rein informativ auf Basis öffentlicher Reddit-Daten.

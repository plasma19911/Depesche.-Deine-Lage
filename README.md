# Depesche

Eine schlanke Nachrichten-App mit drei Kanälen — **Deutschland**, **Spandau & Falkensee**
und **Naturwissenschaften** — die nur Meldungen der **letzten 7 Tage** anzeigt und sich per
GitHub Actions selbst aktualisiert. Kein Server, kein API-Schlüssel.

## Wie es funktioniert

- `fetch_news.py` ruft Feeds ab (Google News RSS für Deutschland + die lokale Suche nach
  Spandau/Falkensee, dazu Spektrum, scinexx und wissenschaft.de für die Wissenschaft),
  filtert auf 7 Tage, entfernt Duplikate und schreibt `news.json`.
- `index.html` lädt `news.json` im Browser und zeigt die drei Kanäle an. Läuft als reine
  statische Seite.
- Der GitHub-Workflow führt den Abruf alle 3 Stunden aus und committet die neue `news.json`.

## Einrichtung (einmalig)

1. **Neues Repository** auf GitHub anlegen (z. B. `depesche`), öffentlich.
2. Diese Dateien hochladen:
   ```
   index.html
   fetch_news.py
   requirements.txt
   news.json
   .github/workflows/update-news.yml
   ```
   Wichtig: Der Workflow muss unter dem Pfad `.github/workflows/` liegen.
3. **GitHub Pages aktivieren:** Repo → *Settings* → *Pages* →
   *Build and deployment* → *Source: Deploy from a branch* → Branch `main`, Ordner `/ (root)`
   → *Save*. Nach ein paar Minuten ist die Seite unter
   `https://DEIN-NAME.github.io/depesche/` erreichbar.
4. **Automatik testen:** Repo → *Actions* → *Nachrichten aktualisieren* → *Run workflow*.
   Danach läuft sie alle 3 Stunden von allein.

Falls die Actions keinen Push machen dürfen: Repo → *Settings* → *Actions* → *General* →
*Workflow permissions* → *Read and write permissions* aktivieren.

## Anpassen

- **Quellen / Rubriken:** in `fetch_news.py` oben in der Liste `SECTIONS`. Jede Rubrik hat
  eine Liste von Feed-URLs. Weitere Google-News-Suchen baust du so:
  `https://news.google.com/rss/search?q=DEIN+SUCHWORT%20when:7d&hl=de&gl=DE&ceid=DE:de`
- **Zeitfenster je Kanal:** der Schlüssel `"days"` in der jeweiligen Rubrik in
  `SECTIONS` (aktuell: Deutschland & Weltweit 3 Tage, Spandau/Falkensee &
  Naturwissenschaften 7 Tage). Ohne `"days"` gilt `DEFAULT_DAYS` (7).
- **Anzahl pro Kanal:** `PER_SECTION` (Standard 24).
- **Aktualisierungs-Takt:** `cron` in `update-news.yml` (Zeit in UTC).
- **Name/Farben:** oben im `<style>`-Block von `index.html` (`--de`, `--lok`, `--nat`).

## Lokal testen

```bash
python fetch_news.py          # erzeugt news.json
python -m http.server 8000    # dann http://localhost:8000 öffnen
```

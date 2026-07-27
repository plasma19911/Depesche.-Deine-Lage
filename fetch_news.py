#!/usr/bin/env python3
"""
Ruft Nachrichten fuer drei Rubriken ab, filtert auf die letzten 7 Tage
und schreibt news.json. Quellen: Google News RSS (national + hyperlokale
Suche) und deutsche Wissenschaftsfeeds. Laeuft ohne API-Schluessel.
"""
import json, re, html, socket, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import xml.etree.ElementTree as ET

try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
    _HAS_LANGDETECT = True
except ImportError:
    _HAS_LANGDETECT = False

# Klare Deutsch-Signale: Umlaute/ß oder haeufige Stoppwoerter.
GERMAN_HINT = re.compile(
    r"[äöüß]|\b(der|die|das|und|für|nicht|mit|auf|von|im|ist|wird|"
    r"eine|einen|dem|den|des|nach|über|bei|aus|zum|zur|wegen|gegen)\b",
    re.IGNORECASE,
)


def is_german(title: str, summary: str = "") -> bool:
    text = (title + ". " + summary).strip()
    if len(text) < 3:
        return True
    # Eindeutige deutsche Merkmale -> immer behalten (keine Falsch-Aussortierung).
    if GERMAN_HINT.search(text):
        return True
    if not _HAS_LANGDETECT:
        return True  # ohne Bibliothek nicht filtern
    try:
        return detect(text) == "de"
    except Exception:
        return True

DOMAIN_NAMES = {
    "spektrum.de": "Spektrum", "scinexx.de": "scinexx",
    "wissenschaft.de": "wissenschaft.de",
}

socket.setdefaulttimeout(25)
DEFAULT_DAYS = 7        # Zeitfenster, falls eine Rubrik keins angibt
PER_SECTION = 100
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124 Safari/537.36")

# Rubriken -> Liste von Feed-URLs
SECTIONS = [
    {
        "id": "deutschland",
        "title": "Deutschland",
        "days": 3,
        "feeds": [
            "https://news.google.com/rss?hl=de&gl=DE&ceid=DE:de",
            "https://news.google.com/rss/headlines/section/topic/NATION.de_de/Deutschland?hl=de&gl=DE&ceid=DE:de",
        ],
    },
    {
        "id": "welt",
        "title": "Weltweit",
        "days": 3,
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/WORLD?hl=de&gl=DE&ceid=DE:de",
        ],
    },
    {
        "id": "lokal",
        "title": "Spandau & Falkensee",
        "days": 7,
        "feeds": [
            "https://news.google.com/rss/search?q=Spandau%20when:7d&hl=de&gl=DE&ceid=DE:de",
            "https://news.google.com/rss/search?q=Falkensee%20when:7d&hl=de&gl=DE&ceid=DE:de",
        ],
    },
    {
        "id": "wissenschaft",
        "title": "Naturwissenschaften",
        "days": 7,
        "feeds": [
            "https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/996406",
            "https://www.scinexx.de/feed/",
            "https://www.wissenschaft.de/feed/",
        ],
    },
]

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def clean(text: str, limit: int = 240) -> str:
    if not text:
        return ""
    text = html.unescape(text)
    text = TAG_RE.sub(" ", text)
    text = WS_RE.sub(" ", text).strip()
    # Google News haengt oft " ... - Quelle" Muell an -> abschneiden
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "\u2026"
    return text


def parse_date(entry):
    for tag in ("pubDate", "{http://www.w3.org/2005/Atom}updated",
                "{http://www.w3.org/2005/Atom}published"):
        el = entry.find(tag)
        if el is not None and el.text:
            try:
                dt = parsedate_to_datetime(el.text)
            except (TypeError, ValueError):
                try:
                    dt = datetime.fromisoformat(el.text.replace("Z", "+00:00"))
                except ValueError:
                    continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
    return None


def get(entry, *tags):
    for tag in tags:
        el = entry.find(tag)
        if el is not None and (el.text or el.get("href")):
            return el.text or el.get("href")
    return ""


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    })
    with urllib.request.urlopen(req) as r:
        return r.read()


def source_from_title(title: str):
    # Google News: "Schlagzeile - Quelle"
    if " - " in title:
        head, src = title.rsplit(" - ", 1)
        if 2 <= len(src) <= 40:
            return head.strip(), src.strip()
    return title.strip(), ""


def parse_feed(raw: bytes):
    items = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items
    # RSS <item> und Atom <entry>
    nodes = root.iter("item")
    entries = list(nodes)
    atom = "{http://www.w3.org/2005/Atom}entry"
    entries += list(root.iter(atom))
    for e in entries:
        raw_title = clean(get(e, "title", "{http://www.w3.org/2005/Atom}title"), 200)
        if not raw_title:
            continue
        link = get(e, "link", "{http://www.w3.org/2005/Atom}link")
        summary = clean(get(e, "description", "{http://www.w3.org/2005/Atom}summary",
                            "{http://www.w3.org/2005/Atom}content"))
        dt = parse_date(e)
        src_el = e.find("source")
        source = src_el.text.strip() if src_el is not None and src_el.text else ""
        title, src2 = source_from_title(raw_title)
        source = source or src2
        # bei Fachfeeds keine Quelle im Titel -> Titel behalten
        if not src2:
            title = raw_title
        if not source and link:
            host = urlparse(link).netloc.replace("www.", "")
            source = DOMAIN_NAMES.get(host, host)
        # Zusammenfassung nicht doppelt mit Titel
        if summary and summary.lower().startswith(title.lower()[:30]):
            summary = ""
        items.append({
            "title": title,
            "link": link,
            "summary": summary,
            "source": source,
            "published": dt,
        })
    return items


def main():
    now = datetime.now(timezone.utc)
    out_sections = []
    for sec in SECTIONS:
        days = sec.get("days", DEFAULT_DAYS)
        cutoff = now - timedelta(days=days)
        seen = set()
        collected = []
        for url in sec["feeds"]:
            try:
                raw = fetch(url)
            except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout) as ex:
                print(f"  ! Feed-Fehler {url[:60]}: {ex}")
                continue
            for it in parse_feed(raw):
                dt = it["published"]
                if dt is None or dt < cutoff or dt > now + timedelta(hours=6):
                    continue
                if not is_german(it["title"], it.get("summary", "")):
                    continue
                key = (it["title"][:70].lower())
                if key in seen:
                    continue
                seen.add(key)
                collected.append(it)
        collected.sort(key=lambda x: x["published"], reverse=True)
        collected = collected[:sec.get("limit", PER_SECTION)]
        for it in collected:
            it["published"] = it["published"].isoformat()
        print(f"  {sec['title']:22} {len(collected)} Beitraege (letzte {days} Tage)")
        out_sections.append({
            "id": sec["id"], "title": sec["title"], "days": days, "items": collected,
        })

    data = {
        "generated": now.isoformat(),
        "sections": out_sections,
    }
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    total = sum(len(s["items"]) for s in out_sections)
    print(f"news.json geschrieben: {total} Beitraege gesamt.")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Ruft Nachrichten fuer drei Rubriken ab, filtert auf die letzten 7 Tage
und schreibt news.json. Quellen: Google News RSS (national + hyperlokale
Suche) und deutsche Wissenschaftsfeeds. Laeuft ohne API-Schluessel.
"""
import json, re, html, socket, time, urllib.request, urllib.error
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


# Themen, die aus allen Kanälen ausgeschlossen werden. Zwei Gruppen:
# - WORD_START: Stamm muss am Wortanfang stehen (schützt vor Kollisionen wie
#   "Schmerz" vs. "Merz", "Protestantismus" vs. "Protest", "Merzig" vs. "Merz").
# - ANYWHERE: Stamm darf auch mitten in einem Kompositum stehen, weil deutsche
#   Kriegs-/Konfliktbegriffe oft als Wortende auftauchen ("Irankrieg", "Ukrainekrieg").
_WORD_START = [
    # Politik
    r"bundestag", r"bundesrat", r"bundesregierung", r"bundeskanzler",
    r"kanzleramt", r"koalition", r"minister", r"ministerium", r"parlament",
    r"abgeordnet", r"parteitag", r"parteichef", r"CDU", r"CSU", r"SPD",
    r"AfD", r"grünen-", r"FDP", r"linkspartei", r"BSW", r"wahlkampf",
    r"bundestagswahl", r"landtagswahl", r"europawahl", r"stimmzettel",
    r"opposition", r"gesetzentwurf", r"regierungskoalition",
    r"außenminister", r"innenminister", r"diplomat", r"botschafter",
    r"staatsbesuch", r"gipfeltreffen", r"nato", r"eu-kommission",
    r"un-sicherheitsrat", r"sanktion", r"geopolitik", r"separatist",
    r"präsidentschaftswahl", r"putin", r"selenskyj", r"zelensky",
    r"trump(?!f)", r"\bscholz", r"habeck", r"baerbock", r"pistorius",
    r"wagenknecht", r"weidel", r"merz\b", r"kreml", r"weißen? haus",
    r"regierung", r"geheimdienst", r"militär", r"invasion", r"armee",
    r"streitkräfte", r"sicherheitsabkommen", r"raketenangriff",
    r"luftangriff", r"drohnenangriff", r"luftabwehr", r"raketenabwehr",
    r"protest(?!ant)", r"demonstration", r"einwanderungsbehörde",
    r"einwanderungspolitik", r"asylpolitik", r"flüchtlingspolitik",
    r"abschiebung", r"grenzschutz", r"volksentscheid", r"referendum",
    # Sport
    r"fußballbundesliga", r"bundesliga", r"champions league",
    r"europa league", r"dfb-pokal", r"DFB\b", r"nationalmannschaft",
    r"olympi", r"paralympi", r"weltmeisterschaft", r"europameisterschaft",
    r"handball", r"basketball", r"volleyball", r"eishockey", r"formel 1",
    r"formel-1", r"grand prix", r"tour de france", r"radsport", r"tennis",
    r"golfturnier", r"boxkampf", r"schwergewicht", r"biathlon",
    r"skispringen", r"leichtathletik", r"marathonlauf", r"transfermarkt",
    r"torschütze", r"spielstand", r"halbzeit", r"schiedsrichter",
    r"bundestrainer", r"vereinspräsident", r"meistertitel",
    r"tabellenführer", r"abstiegskampf", r"pokalfinale", r"olympiasieger",
    r"weltmeister", r"medaillenspiegel", r"fifa", r"uefa",
    r"nationalspieler", r"kapitän", r"radprofi", r"etappensieg",
    # Wirtschaft
    r"aktienkurs", r"aktienmarkt", r"börse", r"DAX\b", r"MDAX",
    r"dow jones", r"nasdaq", r"quartalszahlen", r"geschäftszahlen",
    r"jahresbilanz", r"umsatzwachstum", r"umsatzeinbruch",
    r"gewinneinbruch", r"konzernchef", r"finanzchef",
    r"vorstandsvorsitzende", r"aktionäre", r"inflation", r"leitzins",
    r"EZB\b", r"zentralbank", r"wirtschaftswachstum", r"rezession",
    r"konjunktur", r"arbeitsmarkt", r"arbeitslosenquote", r"exportzahlen",
    r"handelsbilanz", r"zollstreit", r"insolvenz", r"sparprogramm",
    r"sparkurs", r"stellenabbau", r"entlassungswelle", r"fusionsplan",
    r"übernahmeangebot", r"börsengang", r"geschäftsbericht",
    r"verbraucherpreise", r"energiepreise", r"rohstoffpreise", r"ölpreis",
    r"gaspreis", r"marktbericht", r"wirtschaftsminister", r"dividende",
    r"kurssturz", r"aktiencrash",
]
_ANYWHERE = [r"krieg", r"kriegsgebiet"]

_word_start_re = re.compile(r"\b(" + "|".join(_WORD_START) + r")\w*", re.IGNORECASE)
_anywhere_re = re.compile("(" + "|".join(_ANYWHERE) + ")", re.IGNORECASE)


def is_excluded(title: str, summary: str = "") -> bool:
    text = title + " " + summary
    return bool(_word_start_re.search(text) or _anywhere_re.search(text))

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
        "title": "Wissenschaft",
        "days": 7,
        "feeds": [
            "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=de&gl=DE&ceid=DE:de",
            "https://www.spektrum.de/alias/rss/spektrum-de-rss-feed/996406",
            "https://www.scinexx.de/feed/",
            "https://www.wissenschaft.de/feed/",
            "https://scienceblogs.de/feed/",
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


def fetch(url: str, retries: int = 3) -> bytes:
    headers = {
        "User-Agent": UA,
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    }
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, socket.timeout) as e:
            last_err = e
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise last_err


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
    # Bisherige Daten laden (Rückfall, falls eine Quelle mal ausfällt).
    previous = {}
    try:
        with open("news.json", encoding="utf-8") as f:
            old = json.load(f)
        for s in old.get("sections", []):
            previous[s["id"]] = s.get("items", [])
    except (FileNotFoundError, ValueError):
        pass

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
                if is_excluded(it["title"], it.get("summary", "")):
                    continue
                key = (it["title"][:70].lower())
                if key in seen:
                    continue
                seen.add(key)
                collected.append(it)
            time.sleep(1)  # höflich zwischen Feeds, senkt Rate-Limit-Risiko
        collected.sort(key=lambda x: x["published"], reverse=True)
        collected = collected[:sec.get("limit", PER_SECTION)]
        for it in collected:
            it["published"] = it["published"].isoformat()

        # Rückfall: kam nichts (z. B. Quelle down), letzte Daten im Fenster behalten.
        if not collected and previous.get(sec["id"]):
            kept = []
            for it in previous[sec["id"]]:
                try:
                    dt = datetime.fromisoformat(it["published"])
                except (KeyError, ValueError):
                    continue
                if dt >= cutoff:
                    kept.append(it)
            collected = kept
            if kept:
                print(f"  (Rückfall auf {len(kept)} gespeicherte Beiträge)")
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

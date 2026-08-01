"""Resonanz: was zu einem Thema WIRKLICH ankommt — gemessen an Zustimmung, nicht an
Suchmaschinen-Rang.

Eine Suchmaschine beantwortet "was gibt es dazu". Vor einem Video, einer Kaltakquise
oder einer Produktentscheidung ist die nuetzlichere Frage aber "worueber reden Leute
gerade, und was davon traegt". Das steht in Upvotes und Kommentarzahlen.

Zwei Quellen, gemessen am 29.07.2026:

  * Hacker News — die Algolia-API des Projekts. Laeuft OHNE alles: kein Schluessel,
    kein Konto, keine Konfiguration. Technik, Werkzeuge, Startups, Produktfragen.
  * Reddit — nur noch mit EIGENEN App-Zugangsdaten. Die oeffentliche search.json
    antwortet inzwischen mit 403 (Server 'snooserv' — Reddits eigene Sperre, kein
    Rate-Limit), und zwar fuer jede Variante: www, old, /r/<sub>/top.json. Fehlen die
    Zugangsdaten, wird die Quelle sauber uebersprungen statt in einen Fehler zu laufen.

Geprueft und VERWORFEN: Bluesky (403 von einem CDN-Knoten) und Lemmy — dessen Suche
ignoriert die Anfrage weitgehend: bei sort=Relevance kamen null Treffer, bei TopMonth
war einer von vier thematisch passend. Rauschen ist in einem Werkzeug, dessen ganzer
Wert Signal ist, schlimmer als eine fehlende Quelle.

Was hier NICHT steht, ist Absicht: Quellen, die eine eingeloggte Browser-Sitzung
verlangen (X, TikTok, Instagram). Eine Skript-App mit eigener Client-ID ist etwas
anderes als ein angezapfter Login — die eine ist ein Leseausweis, die andere ein
Generalschluessel zum Konto.

Wertung: Punkte + 2x Kommentare. Kommentare wiegen doppelt, weil ein Klick auf den
Pfeil nach oben billig ist und ein geschriebener Kommentar nicht — Diskussion ist das
staerkere Signal fuer "das beschaeftigt Leute". Die Rohzahlen stehen trotzdem in jeder
Zeile, damit die Gewichtung nachvollziehbar bleibt und nicht geglaubt werden muss.
"""
from __future__ import annotations

import time
from urllib.parse import quote_plus

import httpx

from core import config as _cfg
from core.kernel import events

_TIMEOUT_S = 12
# Reddit weist Anfragen ohne eigene Kennung ab (429). Kein Konto, kein Schluessel —
# nur ein ehrlicher Name, wie es die API-Regeln verlangen.
_KOPF = {"User-Agent": "kira-resonanz/1.0 (persoenlicher Assistent, keine Sammlung)"}


def _reddit_zeitfenster(tage: int) -> str:
    if tage <= 1:
        return "day"
    if tage <= 7:
        return "week"
    if tage <= 31:
        return "month"
    return "year"


def _reddit_token() -> str:
    """Zugangs-Token aus EIGENEN App-Zugangsdaten (Skript-App, kostenlos).

    Messung 29.07.2026: die oeffentliche search.json antwortet inzwischen mit 403
    (Server 'snooserv' — Reddits eigene Sperre, kein Rate-Limit), und zwar fuer jede
    Variante: www, old, /r/<sub>/top.json. Ohne Zugangsdaten geht dort nichts mehr.

    Der Weg darueber ist trotzdem harmlos: eine Skript-App liefert Client-ID und
    Secret fuer den EIGENEN Account, keine Browser-Sitzung wird angezapft, und ein
    reines Lese-Token sieht nur, was oeffentlich ist."""
    import os

    cid = (os.getenv("REDDIT_CLIENT_ID") or "").strip()
    secret = (os.getenv("REDDIT_CLIENT_SECRET") or "").strip()
    if not cid or not secret:
        return ""
    r = httpx.post("https://www.reddit.com/api/v1/access_token",
                   data={"grant_type": "client_credentials"},
                   auth=(cid, secret), headers=_KOPF, timeout=_TIMEOUT_S)
    if r.status_code != 200:
        return ""
    return str(r.json().get("access_token") or "")


def _reddit(thema: str, tage: int, roh: int) -> tuple[list[dict], str]:
    token = _reddit_token()
    if not token:
        return [], ("reddit: uebersprungen — braucht eigene App-Zugangsdaten "
                    "(REDDIT_CLIENT_ID/REDDIT_CLIENT_SECRET), die oeffentliche API ist zu")
    kopf = dict(_KOPF, Authorization=f"bearer {token}")
    url = (f"https://oauth.reddit.com/search?q={quote_plus(thema)}"
           f"&sort=top&t={_reddit_zeitfenster(tage)}&limit={roh}")
    r = httpx.get(url, headers=kopf, timeout=_TIMEOUT_S, follow_redirects=True)
    if r.status_code != 200:
        return [], f"reddit: HTTP {r.status_code}"
    kinder = (r.json().get("data") or {}).get("children") or []
    grenze = time.time() - tage * 86400
    out = []
    for k in kinder:
        d = k.get("data") or {}
        ts = float(d.get("created_utc") or 0)
        if ts < grenze:
            continue
        out.append({
            "quelle": "reddit",
            "titel": str(d.get("title") or "").strip(),
            "punkte": int(d.get("score") or 0),
            "kommentare": int(d.get("num_comments") or 0),
            "ts": ts,
            "wo": f"r/{d.get('subreddit') or '?'}",
            "url": "https://www.reddit.com" + str(d.get("permalink") or ""),
        })
    return out, ""


def _hackernews(thema: str, tage: int, roh: int) -> tuple[list[dict], str]:
    seit = int(time.time() - tage * 86400)
    url = (f"https://hn.algolia.com/api/v1/search?query={quote_plus(thema)}"
           f"&tags=story&numericFilters=created_at_i>{seit}&hitsPerPage={roh}")
    r = httpx.get(url, headers=_KOPF, timeout=_TIMEOUT_S, follow_redirects=True)
    if r.status_code != 200:
        return [], f"hackernews: HTTP {r.status_code}"
    out = []
    for h in r.json().get("hits") or []:
        titel = str(h.get("title") or h.get("story_title") or "").strip()
        if not titel:
            continue
        out.append({
            "quelle": "hackernews",
            "titel": titel,
            "punkte": int(h.get("points") or 0),
            "kommentare": int(h.get("num_comments") or 0),
            "ts": float(h.get("created_at_i") or 0),
            "wo": "Hacker News",
            "url": h.get("url") or f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })
    return out, ""


def _wertung(e: dict) -> int:
    """Punkte + 2x Kommentare — Diskussion wiegt schwerer als ein Klick."""
    return int(e.get("punkte") or 0) + 2 * int(e.get("kommentare") or 0)


def suchen(thema: str, tage: int = 30, limit: int = 10) -> tuple[list[dict], list[str]]:
    """Beide Quellen abfragen, zusammenfuehren, nach Resonanz sortieren.

    Eine tote Quelle stoppt die andere nicht — dasselbe Ketten-Muster wie web_search."""
    treffer: list[dict] = []
    hinweise: list[str] = []
    roh = max(25, limit * 3)
    for name, fn in (("reddit", _reddit), ("hackernews", _hackernews)):
        try:
            teil, hinweis = fn(thema, tage, roh)
            treffer.extend(teil)
            if hinweis:
                hinweise.append(hinweis)
        except Exception as e:  # noqa: BLE001 — eine tote Quelle stoppt die Kette nicht
            hinweise.append(f"{name}: {type(e).__name__}")
    treffer.sort(key=_wertung, reverse=True)
    return treffer[:limit], hinweise


def _alter(ts: float) -> str:
    tage = max(0, int((time.time() - ts) / 86400))
    if tage == 0:
        return "heute"
    return "gestern" if tage == 1 else f"vor {tage} Tagen"


def bericht(thema: str, tage: int = 30, limit: int = 10) -> str:
    """Fertiger Text fuers Modell: sortierte Liste mit sichtbaren Rohzahlen."""
    if _cfg.outbound_blocked():
        return ("Resonanz ist in diesem Lauf abgeschaltet (Firewall: kein Netz nach "
                "draussen). Ohne Netz gibt es keine echten Zahlen — erfinde keine.")
    thema = str(thema or "").strip()
    if not thema:
        return "Fehler: resonanz braucht ein thema (z.B. resonanz(thema=\"Kaltakquise\"))."
    treffer, hinweise = suchen(thema, tage=tage, limit=limit)
    events.emit("resonanz_gesucht", {"thema": thema[:80], "tage": tage,
                                     "treffer": len(treffer), "hinweise": hinweise[:3]})
    if not treffer:
        rest = f" ({'; '.join(hinweise)})" if hinweise else ""
        return (f"Keine Beitraege zu '{thema}' in den letzten {tage} Tagen gefunden{rest}. "
                "Das heisst: dazu wird gerade wenig geschrieben — sag das ruhig so, "
                "statt etwas zu erfinden.")
    zeilen = [f"Resonanz zu '{thema}', letzte {tage} Tage "
              f"(sortiert nach Punkten + 2x Kommentaren):"]
    for i, e in enumerate(treffer, 1):
        zeilen.append(
            f"{i}. [{e['wo']}] {e['titel'][:150]}\n"
            f"   {e['punkte']} Punkte, {e['kommentare']} Kommentare · {_alter(e['ts'])} · {e['url']}")
    if hinweise:
        zeilen.append(f"(Nicht erreichbar: {'; '.join(hinweise)})")
    return "\n".join(zeilen)

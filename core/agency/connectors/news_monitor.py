"""Web-/News-Monitor (rein lesend): Kira ueberwacht Feeds/Themen und meldet Neues.

Sicher als erster echter Connector: nur LESEN (RSS-Feeds + Web-Suche), keine Aussen-Aktionen.
Pro Beobachtung (watch) wird dedupliziert (gesehene Eintraege gemerkt) und nur WIRKLICH Neues
gemeldet. Zusammenfassung uebernimmt das lokale Modell (0 EUR). Meldung via Telegram.

watches.json (data/): Liste von {id, kind: feed|search, value, label, interval_min, last_checked, seen[]}.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import xml.etree.ElementTree as ET

import httpx

from core.config import CONFIG, ROOT
from core.kernel import events, llm_router

_UA = {"User-Agent": "Mozilla/5.0 (Kira News Monitor)"}
WATCHES = ROOT / "data" / "watches.json"


def _load() -> list[dict]:
    if WATCHES.exists():
        try:
            return json.loads(WATCHES.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save(w: list[dict]) -> None:
    WATCHES.parent.mkdir(parents=True, exist_ok=True)
    WATCHES.write_text(json.dumps(w, ensure_ascii=False, indent=2), encoding="utf-8")


def _hash(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "replace")).hexdigest()[:12]


def list_watches() -> list[dict]:
    # ohne das (potenziell grosse) seen-Feld fuers Dashboard
    return [{k: v for k, v in w.items() if k != "seen"} for w in _load()]


def add_watch(kind: str, value: str, label: str = "") -> dict:
    w = _load()
    item = {
        "id": _hash(kind + value + str(time.time())),
        "kind": "feed" if kind == "feed" else "search",
        "value": value.strip(),
        "label": (label or value).strip(),
        "interval_min": 60,
        "last_checked": 0,
        "seen": [],
    }
    w.append(item)
    _save(w)
    return {k: v for k, v in item.items() if k != "seen"}


def remove_watch(wid: str) -> bool:
    w = _load()
    n = [x for x in w if x.get("id") != wid]
    _save(n)
    return len(n) != len(w)


def _feed_items(url: str) -> list[dict]:
    r = httpx.get(url, timeout=20, headers=_UA, follow_redirects=True)
    r.raise_for_status()
    try:
        root = ET.fromstring(r.content)
    except Exception:
        return []
    items: list[dict] = []
    for it in root.iter():
        tag = it.tag.lower().rsplit("}", 1)[-1]
        if tag not in ("item", "entry"):
            continue
        title = link = guid = ""
        for ch in it:
            t = ch.tag.lower().rsplit("}", 1)[-1]
            if t == "title":
                title = (ch.text or "").strip()
            elif t == "link":
                link = (ch.text or "").strip() or ch.attrib.get("href", "")
            elif t in ("guid", "id"):
                guid = (ch.text or "").strip()
        uid = guid or link or title
        if uid:
            items.append({"id": _hash(uid), "title": title or "(ohne Titel)", "link": link})
    return items


def _search_items(query: str) -> list[dict]:
    from core.agency.tools.builtin import web_search

    raw = web_search(query, max_results=6)
    lines = [ln for ln in raw.splitlines() if ln.strip()]
    items: list[dict] = []
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("- "):
            title = lines[i].lstrip()[2:].strip()
            link = lines[i + 1].strip() if i + 1 < len(lines) and not lines[i + 1].lstrip().startswith("- ") else ""
            items.append({"id": _hash(link or title), "title": title, "link": link})
            i += 2 if link else 1
        else:
            i += 1
    return items


def check_watch(w: dict, force: bool = False) -> dict:
    now = time.time()
    if not force and (now - w.get("last_checked", 0)) < w.get("interval_min", 60) * 60:
        return {"id": w["id"], "skipped": True, "new": []}
    try:
        items = _feed_items(w["value"]) if w["kind"] == "feed" else _search_items(w["value"])
    except Exception as e:  # noqa: BLE001
        return {"id": w["id"], "error": str(e), "new": []}
    seen = set(w.get("seen", []))
    first_run = not w.get("last_checked")
    new = [it for it in items if it["id"] not in seen]
    w["last_checked"] = now
    w["seen"] = ([it["id"] for it in items] + w.get("seen", []))[:300]
    # Beim allerersten Lauf nicht den ganzen Feed als "neu" melden -> nur merken.
    return {"id": w["id"], "label": w["label"], "new": [] if first_run else new, "total": len(items)}


def _summarize(label: str, new_items: list[dict]) -> str:
    titles = "\n".join(f"- {it['title']} ({it['link']})" for it in new_items[:8])
    try:
        r = llm_router.complete(
            [
                {"role": "system", "content": "Du fasst Nachrichten-Schlagzeilen knapp auf Deutsch zusammen. "
                 "Gib AUSSCHLIESSLICH 2 bis 4 Stichpunkte aus, jeder beginnt mit '- '. KEINE Einleitung, "
                 "KEINE Selbstvorstellung, niemals 'Ich bin', kein Modell- oder Firmenname, keine Sternchen."},
                {"role": "user", "content": f"Quelle: {label}\nNeue Schlagzeilen:\n{titles}\n\nFasse zusammen:"},
            ],
            task_type="chat",
        )
        text = r["text"].strip()
        bullets = [
            ln.rstrip()
            for ln in text.splitlines()
            if ln.lstrip().startswith(("-", "•", "*"))
            and not any(bad in ln for bad in ("Empero", "Qwythos", "Ich bin", "ich bin"))
        ]
        return "\n".join(bullets) if bullets else titles
    except Exception:
        return titles


def _notify(text: str) -> None:
    try:
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        chat = CONFIG.get("channels", {}).get("telegram", {}).get("allowed_chat_id")
        if token and chat:
            httpx.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat, "text": text[:4000]},
                timeout=15,
            )
    except Exception as e:  # noqa: BLE001
        events.emit("notify_error", {"error": str(e)})


def run_all(force: bool = False, notify: bool = True) -> dict:
    """Alle Beobachtungen pruefen (rate-limited pro watch), Neues zusammenfassen + melden."""
    w = _load()
    if not w:
        return {"checked": 0, "digests": []}
    digests = []
    for watch in w:
        res = check_watch(watch, force=force)
        if res.get("new"):
            summary = _summarize(watch["label"], res["new"])
            digests.append({"label": watch["label"], "count": len(res["new"]), "summary": summary})
            events.emit("monitor_new", {"label": watch["label"], "count": len(res["new"]), "summary": summary})
            if notify:
                _notify(f"📰 {watch['label']} — {len(res['new'])} neu:\n{summary}")
    _save(w)  # aktualisierten Zustand (last_checked/seen) sichern
    return {"checked": len(w), "digests": digests}

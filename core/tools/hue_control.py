"""
Hue Bridge Control — Kira's Lichtsteuerung.

Bridge: 192.168.178.20
API-Key: data/hue_key.txt
"""

import json
import urllib.request
import urllib.error
from pathlib import Path

BRIDGE_IP = "192.168.178.20"
KEY_FILE = Path(__file__).parent.parent.parent / "data" / "hue_key.txt"

# ── Farb-Mapping (Hue-Werte) ──────────────────────────────────────────
COLOR_MAP = {
    "rot": 0,
    "orange": 6000,
    "gelb": 11000,
    "gruen": 22000,
    "tuerkis": 28000,
    "blau": 46000,
    "lila": 50000,
    "pink": 55000,
    "weiss": None,       # ct-Modus
    "warmweiss": None,   # ct-Modus
    "kaltweiss": None,   # ct-Modus
}

def _key() -> str:
    """Liest den API-Key aus data/hue_key.txt."""
    if not KEY_FILE.exists():
        raise FileNotFoundError(f"API-Key nicht gefunden: {KEY_FILE}")
    return KEY_FILE.read_text().strip()

def _url(path: str) -> str:
    """Baut eine Hue-API-URL."""
    return f"http://{BRIDGE_IP}/api/{_key()}{path}"

def _req(method: str, path: str, data: dict | None = None) -> dict:
    """Sendet einen Request an die Hue-Bridge und gibt JSON zurueck."""
    url = _url(path)
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}
    except urllib.error.URLError as e:
        return {"error": str(e.reason)}

# ── Oeffentliche API ──────────────────────────────────────────────────

def list_lights() -> dict:
    """Listet alle Lampen (ID, Name, Typ, Status)."""
    raw = _req("GET", "/lights")
    if "error" in raw and isinstance(raw.get("error"), int):
        return raw
    result = {}
    for lid, info in raw.items():
        state = info.get("state", {})
        result[lid] = {
            "name": info.get("name", "?"),
            "type": info.get("type", "?"),
            "on": state.get("on", False),
            "bri": state.get("bri", 0),
            "hue": state.get("hue", 0),
            "sat": state.get("sat", 0),
            "reachable": state.get("reachable", False),
        }
    return result

def get_light_state(light_id: int) -> dict:
    """Gibt den vollen Zustand einer Lampe zurueck."""
    raw = _req("GET", f"/lights/{light_id}")
    if "error" in raw and isinstance(raw.get("error"), int):
        return raw
    return raw

def light_on_off(light_id: int, on: bool) -> dict:
    """Schaltet eine Lampe ein (True) oder aus (False)."""
    return _req("PUT", f"/lights/{light_id}/state", {"on": on})

def set_brightness(light_id: int, bri: int) -> dict:
    """Setzt Helligkeit (1–254)."""
    bri = max(1, min(254, int(bri)))
    return _req("PUT", f"/lights/{light_id}/state", {"bri": bri})

def set_color(light_id: int, color_name: str) -> dict:
    """Setzt Farbe per Name (rot, gruen, blau, …)."""
    name = color_name.lower().strip()
    if name not in COLOR_MAP:
        return {"error": f"Unbekannte Farbe: {name}", "known": list(COLOR_MAP.keys())}
    hue = COLOR_MAP[name]
    if hue is None:
        # Weiss-Modus via ct
        ct_map = {"weiss": 300, "warmweiss": 500, "kaltweiss": 153}
        ct = ct_map.get(name, 300)
        return _req("PUT", f"/lights/{light_id}/state", {"ct": ct, "sat": 0})
    return _req("PUT", f"/lights/{light_id}/state", {"hue": hue, "sat": 254})


# ── CLI (fuer manuelle Tests) ─────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("hue_control: list | on <id> | off <id> | bri <id> <1-254> | color <id> <name> | state <id>")
        sys.exit(0)
    cmd = sys.argv[1]
    try:
        if cmd == "list":
            for lid, info in list_lights().items():
                print(f"  {lid}: {info['name']} ({info['type']}) on={info['on']} bri={info['bri']}")
        elif cmd == "on":
            print(light_on_off(int(sys.argv[2]), True))
        elif cmd == "off":
            print(light_on_off(int(sys.argv[2]), False))
        elif cmd == "bri":
            print(set_brightness(int(sys.argv[2]), int(sys.argv[3])))
        elif cmd == "color":
            print(set_color(int(sys.argv[2]), sys.argv[3]))
        elif cmd == "state":
            print(json.dumps(get_light_state(int(sys.argv[2])), indent=2))
        else:
            print(f"Unbekannt: {cmd}")
    except (IndexError, ValueError) as e:
        print(f"Fehler: {e}")
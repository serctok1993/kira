"""Zentrale Konfiguration: laedt config.yaml + .env + Zugangs-Tresor, definiert Pfade."""
from __future__ import annotations

import os

from pathlib import Path

import yaml
from dotenv import load_dotenv

# Datenwurzel: normal aus __file__ abgeleitet (Live byte-identisch). Eine Sandbox kann sie
# ueber KIRA_ROOT/KIRA_DATA_DIR umlenken (Testumgebung / Coding-Benchmark im git-Worktree) —
# ohne gesetzte Env aendert sich NICHTS.
# KIRA_TEST_DATA_DIR (W0-Fund 12.07.): automatische Wegwerf-Datenwurzel der Testsuite
# (tests/conftest.py). Bewusst ein EIGENER Schluessel und NICHT KIRA_DATA_DIR: sandbox_active()
# bleibt False -> suppress_repo_writes() greift in Tests weiter (Git-/Verify-Pfade bleiben
# No-Ops). Vorher schrieben Tests ohne eigenes Monkeypatching in die LIVE state.db —
# Test-Events/-Fakten/-Tuning-Exporte landeten im echten Gedaechtnis (Fehlalarme B5/B6).
ROOT = Path(os.getenv("KIRA_ROOT") or Path(__file__).resolve().parent.parent).resolve()  # kira/
DATA_DIR = Path(os.getenv("KIRA_DATA_DIR") or os.getenv("KIRA_TEST_DATA_DIR")
                or (ROOT / "data")).resolve()
MIND_DIR = ROOT / "core" / "mind"
DB_PATH = DATA_DIR / "state.db"
CONFIG_PATH = ROOT / "config.yaml"


def test_mode() -> bool:
    """True im Testmodus: explizit via KIRA_TEST_MODE oder automatisch unter pytest. Guards, die
    Aussen-Wirkungen (Mail/Telegram/Cloud-Budget) verhindern, haengen hieran. Ohne Flag: False."""
    return bool(os.getenv("KIRA_TEST_MODE") or os.getenv("PYTEST_CURRENT_TEST"))


def sandbox_active() -> bool:
    """True, wenn ein eigener Sandbox-Datenpfad gesetzt ist (KIRA_ROOT/KIRA_DATA_DIR) — dann
    laeuft ein echter, isolierter Lauf (z.B. Coding-Benchmark im git-Worktree)."""
    return bool(os.getenv("KIRA_ROOT") or os.getenv("KIRA_DATA_DIR"))


def suppress_repo_writes() -> bool:
    """True nur im blanken Testmodus OHNE Sandbox: dann sind Git-/Verify-Schreibpfade No-Ops
    (pytest fasst das Live-Repo nie an). In einer aktiven Sandbox laufen sie voll real — nur
    eingesperrt im Worktree."""
    return test_mode() and not sandbox_active()


def worktree() -> bool:
    """True, wenn ROOT ein git-WORKTREE ist: dort ist .git eine DATEI (gitdir:-Zeiger),
    im Hauptrepo ein Verzeichnis. Vorfall 18./19.07.: der Desktop-LNK zeigte in einen
    alten Worktree — dort bootete eine Alt-Kira mit leerem data/ (setup_required) und
    altem Code-Stand, deren Mission am Verify vorbei ins Hauptrepo schrieb."""
    try:
        return (Path(ROOT) / ".git").is_file()
    except OSError:
        return False


def hauptrepo() -> Path | None:
    """Wurzel des HAUPTREPOS, wenn ROOT ein Worktree ist — aus dem gitdir:-Zeiger der
    .git-DATEI (<haupt>/.git/worktrees/<name>). Sonst (oder bei kaputtem Zeiger): None."""
    try:
        if not worktree():
            return None
        zeile = (Path(ROOT) / ".git").read_text(encoding="utf-8", errors="replace").strip()
        if not zeile.lower().startswith("gitdir:"):
            return None
        gitdir = Path(zeile.split(":", 1)[1].strip())
        if gitdir.parent.name == "worktrees" and gitdir.parent.parent.name == ".git":
            return gitdir.parent.parent.parent.resolve()
    except OSError:
        return None
    return None


def dienststart_verweigert() -> str | None:
    """Klartext-Veto, wenn ein DIENST (Supervisor/Desktop-App) aus einem git-Worktree
    starten will — ohne bewusste Sandbox (KIRA_ROOT/KIRA_DATA_DIR, z.B. Benchmark).
    None = Start erlaubt."""
    if not worktree() or sandbox_active():
        return None
    return (f"START VERWEIGERT: {ROOT} ist ein git-WORKTREE (.git ist eine Datei) — von "
            "hier bootet sonst eine Alt-Kira mit leerem data/ (setup_required) und altem "
            "Code-Stand. Dienste starten NUR aus dem Hauptrepo; bewusste Sandbox-Laeufe "
            "setzen KIRA_ROOT/KIRA_DATA_DIR.")


def outbound_blocked() -> bool:
    """True, wenn Aussen-Wirkungen (Mail, Telegram, Cloud-LLM-Spend, externe Dienste) unterdrueckt
    werden sollen — gesetzt via KIRA_NO_OUTBOUND, z.B. vom Benchmark-Runner in seiner Sandbox.
    Standard: AUS. Im Normalbetrieb UND in der normalen Testsuite also null Verhaltensaenderung —
    nur ein Lauf, der die Firewall bewusst anschaltet, wird stillgelegt."""
    return bool(os.getenv("KIRA_NO_OUTBOUND"))


# .env laden (still, falls nicht vorhanden)
load_dotenv(ROOT / ".env")


def _load_vault_secrets() -> None:
    """Zugaenge aus dem Tresor (data/secrets.json) in die Umgebung laden — damit JEDER
    Prozess (Cockpit, Telegram-Bot, Supervisor, Runner), der core.config importiert, sie
    sieht. Ohne das lebte ein im Cockpit eingegebener Key nur im Cockpit-Prozess und war
    beim Neustart weg — der separate Bot sah ihn NIE (ELEVENLABS/TTS blieb stumm).
    .env hat Vorrang (setdefault): explizit gesetzte Werte werden nicht ueberschrieben.
    Direkt hier statt via core.governance.secrets, um einen Import-Zyklus zu vermeiden."""
    try:
        import json as _j

        f = DATA_DIR / "secrets.json"
        if not f.exists():
            return
        data = _j.loads(f.read_text(encoding="utf-8"))
        for k, v in (data.get("secrets") or {}).items():
            if v and str(k) not in os.environ:
                os.environ[str(k)] = str(v)
    except Exception:  # noqa: BLE001 — fehlender/kaputter Tresor darf den Start nie brechen
        pass


_load_vault_secrets()


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CONFIG = load_config()


def feature_on(name: str) -> bool:
    """Feature-Flag (config.yaml features:) — unbekannte Namen sind AUS (fail-closed;
    so laesst sich ein Werkzeug mit feature='legacy' stilllegen, ohne die Config
    anzufassen). Liest CONFIG pro Aufruf -> set_override('features.x', True) wirkt
    sofort, ohne Neustart."""
    f = CONFIG.get("features") or {}
    return bool(f.get(name, False))


# Datenverzeichnis sicherstellen
DATA_DIR.mkdir(parents=True, exist_ok=True)


def apply_model_overrides(d: dict) -> None:
    """Laufzeit-Overrides ueber die models-Sektion legen (Modellwahl, Provider).

    So bleibt config.yaml (mit Kommentaren) unangetastet; geaendert wird nur
    data/models.json zur Laufzeit.
    """
    m = CONFIG.setdefault("models", {})
    if "default" in d:
        m["default"] = d["default"]
    if "routing" in d:
        m.setdefault("routing", {}).update(d["routing"])
    if "escalation_model" in d:
        m["escalation_model"] = d["escalation_model"]
    if "providers" in d:
        m.setdefault("providers", {}).update(d["providers"])
    for key in ("num_ctx", "max_tokens", "temperature", "keep_alive"):
        if key in d:
            m[key] = d[key]


# Beim Start vorhandene Overrides einspielen
_MODEL_OVERRIDE = DATA_DIR / "models.json"
if _MODEL_OVERRIDE.exists():
    import json as _json

    try:
        apply_model_overrides(_json.loads(_MODEL_OVERRIDE.read_text(encoding="utf-8")))
    except Exception:
        pass


# Allgemeine Laufzeit-Overrides (data/overrides.json) ueber config.yaml legen -> config.yaml
# bleibt mit Kommentaren unangetastet, Aenderungen ueberleben Neustarts.
_OVERRIDE_FILE = DATA_DIR / "overrides.json"


def _apply_overrides(cfg: dict, ov: dict) -> None:
    for path, val in ov.items():
        keys = str(path).split(".")
        d = cfg
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = val


def set_override(path: str, value) -> None:
    """Einen Config-Pfad (z.B. 'mission.goal') zur Laufzeit setzen + persistieren."""
    import json as _jo

    ov: dict = {}
    if _OVERRIDE_FILE.exists():
        try:
            ov = _jo.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except Exception:
            ov = {}
    ov[path] = value
    from core.kernel.fs import atomic_write as _aw
    _aw(_OVERRIDE_FILE, _jo.dumps(ov, indent=2, ensure_ascii=False))
    _apply_overrides(CONFIG, {path: value})


def _ov_mtime(p) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


_OV_MTIMES: dict[str, float] = {}


def refresh_overrides() -> bool:
    """Laufzeit-Overrides (data/models.json + data/overrides.json) per mtime nachladen.

    Fuer LANGLAEUFER-Prozesse (Telegram-Bot, Runner): set_role/set_override schreiben
    die Dateien im SERVER-Prozess und patchen nur DESSEN CONFIG — ohne diesen Refresh
    fuhr der Bot bis zum Neustart auf dem alten Modell (Live-Fund 17.07.:
    model_role_set um 10:57, alle Bot-Calls liefen weiter auf dem Vorgaenger).
    Billig: zwei stat()-Aufrufe; neu gebaut wird nur bei echter Aenderung.
    True = CONFIG wurde in place neu aufgebaut (alle Import-Referenzen sehen es)."""
    import json as _jr

    m1, m2 = _ov_mtime(_MODEL_OVERRIDE), _ov_mtime(_OVERRIDE_FILE)
    if _OV_MTIMES.get("models") == m1 and _OV_MTIMES.get("overrides") == m2:
        return False
    _OV_MTIMES["models"], _OV_MTIMES["overrides"] = m1, m2
    frisch = load_config()
    CONFIG.clear()
    CONFIG.update(frisch)
    if _MODEL_OVERRIDE.exists():
        try:
            apply_model_overrides(_jr.loads(_MODEL_OVERRIDE.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    if _OVERRIDE_FILE.exists():
        try:
            _apply_overrides(CONFIG, _jr.loads(_OVERRIDE_FILE.read_text(encoding="utf-8")))
        except Exception:  # noqa: BLE001
            pass
    return True


def remove_overrides(prefixes: tuple[str, ...] | list[str]) -> int:
    """Overrides entfernen (W3 Werkszustand): exakter Pfad ODER Praefix ('identity'
    trifft 'identity.user'). CONFIG wird danach IN PLACE frisch aufgebaut (config.yaml
    + models.json + Rest-Overrides) — alle 'from core.config import CONFIG'-Referenzen
    sehen den neuen Stand sofort. Rueckgabe: Anzahl entfernter Eintraege."""
    import json as _jo

    ov: dict = {}
    if _OVERRIDE_FILE.exists():
        try:
            ov = _jo.loads(_OVERRIDE_FILE.read_text(encoding="utf-8"))
        except Exception:
            ov = {}
    def _weg(pfad: str) -> bool:
        return any(pfad == p or pfad.startswith(p + ".") for p in prefixes)
    rest = {k: v for k, v in ov.items() if not _weg(k)}
    entfernt = len(ov) - len(rest)
    if entfernt:
        from core.kernel.fs import atomic_write as _aw
        _aw(_OVERRIDE_FILE, _jo.dumps(rest, indent=2, ensure_ascii=False))
        frisch = load_config()
        CONFIG.clear()
        CONFIG.update(frisch)
        if _MODEL_OVERRIDE.exists():
            try:
                apply_model_overrides(_jo.loads(_MODEL_OVERRIDE.read_text(encoding="utf-8")))
            except Exception:
                pass
        _apply_overrides(CONFIG, rest)
    return entfernt


if _OVERRIDE_FILE.exists():
    import json as _json3

    try:
        _apply_overrides(CONFIG, _json3.loads(_OVERRIDE_FILE.read_text(encoding="utf-8")))
    except Exception:
        pass

# Stand der Override-Dateien stempeln: refresh_overrides() baut nur bei ECHTER Aenderung neu
_OV_MTIMES.update({"models": _ov_mtime(_MODEL_OVERRIDE), "overrides": _ov_mtime(_OVERRIDE_FILE)})

# Zugaenge/Secrets aus data/secrets.json in die Umgebung laden (write-only, gitignored)
_SECRETS_FILE = DATA_DIR / "secrets.json"
if _SECRETS_FILE.exists():
    import json as _json2
    import os as _os

    try:
        for _k, _v in (_json2.loads(_SECRETS_FILE.read_text(encoding="utf-8")).get("secrets") or {}).items():
            if _v:
                _os.environ[_k] = str(_v)
    except Exception:
        pass

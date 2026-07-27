"""Doctor: Kiras Selbst-Check — Modelle, Zugaenge, Abhaengigkeiten, Umgebung (S5).

check() ist strukturiert, wirft NIE und kostet 0 Tokens — laeuft woechentlich
als Wartung im Runner (doctor_report-Event, Telegram nur bei Problemen) und
manuell: uv run python -m core.kernel.doctor (macht zusaetzlich einen Test-Call).
"""
from __future__ import annotations

import os
import shutil
import socket

from core.config import CONFIG, DB_PATH, ROOT
from core.kernel import events, llm_router


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            return s.connect_ex((host, port)) == 0
    except Exception:  # noqa: BLE001
        return False


def check(test_call: bool = False) -> dict:
    """Struktur-Report + problems[]-Liste. Jede Sektion fail-soft."""
    rep: dict = {"problems": []}
    prob = rep["problems"].append

    try:
        models = CONFIG.get("models", {})
        rep["default_model"] = models.get("default")
        rep["local_fallback"] = models.get("local_fallback")
        routing = {}
        for tt in ("chat", "reason", "bulk", "classify", "worker"):
            m, fb = llm_router.resolve_model(tt)
            routing[tt] = {"model": m, "fallback": bool(fb)}
        rep["routing"] = routing
        if all(v["fallback"] for v in routing.values()):
            prob("Ich laufe komplett auf dem lokalen Modell, weil kein Cloud-Schluessel greift. "
                 "Folge: schwaechere Antworten bei schweren Aufgaben. "
                 "Zu tun: API-Schluessel im Cockpit pruefen (Modelle).")
        # Fable-Review-Regel (flexibel, nichts festgenagelt): die SPITZE (escalation_model) hat
        # im Router Vorrang vor reason. Steht sie auf dem Massen-Modell (chat/bulk) oder lokal,
        # laufen code:/plan:/Richter aufs schwaechste Glied — laut warnen, der Nutzer entscheidet.
        esc = models.get("escalation_model") or ""
        mass = {routing.get("chat", {}).get("model"), routing.get("bulk", {}).get("model")}
        reason_m = routing.get("reason", {}).get("model")
        if esc and esc != reason_m and (esc in mass or esc.startswith("ollama")):
            prob(f"Fuer die schweren Aufgaben (Coden, Planen, Pruefen) ist das kleine Modell "
                 f"eingestellt ({esc}) statt des starken ({reason_m}). Folge: schlechtere "
                 f"Ergebnisse genau dort, wo Qualitaet zaehlt. "
                 f"Zu tun: Cockpit -> Modelle -> Eskalation.")
    except Exception as e:  # noqa: BLE001
        prob(f"Ich kann nicht feststellen, welches Modell wofuer zustaendig ist. "
             f"Zu tun: Modell-Einstellungen im Cockpit ansehen. (Technisch: {e})")

    try:
        keys = {env: bool(os.getenv(env)) for env in sorted(set(llm_router._PROVIDER_KEYS.values()))}
        rep["api_keys"] = keys
    except Exception:  # noqa: BLE001
        rep["api_keys"] = {}

    rep["ollama"] = _port_open(11434)
    if not rep["ollama"]:
        prob("Das lokale Modell antwortet nicht (Ollama laeuft nicht). Folge: alles geht "
             "ueber die Cloud — das kostet Geld — und mein Gedaechtnis findet nur noch "
             "per Stichwort statt nach Bedeutung. Zu tun: Ollama starten.")

    rep["node"] = bool(shutil.which("node"))
    rep["npx"] = bool(shutil.which("npx"))
    if not rep["npx"]:
        prob("Node.js fehlt auf dem Rechner. Folge: die Zusatz-Werkzeuge (GitHub, Supabase) "
             "stehen mir nicht zur Verfuegung. Zu tun: Node.js installieren.")

    try:
        du = shutil.disk_usage(ROOT)
        rep["disk_free_gb"] = round(du.free / 1e9, 1)
        if du.free < 5e9:
            prob(f"Die Festplatte wird eng: nur noch {rep['disk_free_gb']} GB frei. "
                 f"Folge: Ablegen und Protokollieren kann fehlschlagen. Zu tun: aufraeumen.")
    except Exception:  # noqa: BLE001
        pass

    imports = {}
    for mod, hard in (("fastapi", True), ("mcp", True), ("playwright", True),
                      ("faster_whisper", False), ("python_multipart", True), ("pypdf", False)):
        try:
            __import__(mod)
            imports[mod] = True
        except Exception:  # noqa: BLE001
            imports[mod] = False
            if hard:
                prob(f"Ein Programmteil laesst sich nicht laden ({mod}). Folge: die Funktionen "
                     f"dahinter fallen aus. Zu tun: im Projektordner 'uv sync' ausfuehren.")
    rep["imports"] = imports
    if not imports.get("pypdf"):
        rep.setdefault("hints", []).append("pypdf fehlt (optional) — PDFs fuers Wissens-Archiv: 'uv add pypdf'.")

    try:
        rep["db_mb"] = round(os.path.getsize(DB_PATH) / 1e6, 1)
        if rep["db_mb"] > 500:
            prob(f"Mein Ereignis-Speicher ist auf {rep['db_mb']} MB gewachsen. Folge: noch nichts, "
                 f"aber es wird traeger. Zu tun: bei Gelegenheit aufraeumen lassen.")
    except Exception:  # noqa: BLE001
        pass

    if test_call:
        try:
            events.init_db()
            r = llm_router.complete(
                [{"role": "user", "content": "Sag in genau fuenf Woertern hallo."}], task_type="chat")
            rep["test_call"] = {"where": "LOKAL" if r["fell_back"] else "CLOUD",
                                "model": r["model"], "latency_s": round(r["latency_s"], 2),
                                "cost_usd": r["cost_usd"], "text": r["text"].strip()[:120]}
        except Exception as e:  # noqa: BLE001
            rep["test_call"] = {"error": str(e)[:200]}
            prob(f"Meine Testanfrage ans Modell kam nicht durch. Folge: im Zweifel antworte ich "
                 f"gerade gar nicht. Zu tun: Internet und API-Schluessel pruefen. "
                 f"(Technisch: {str(e)[:120]})")

    rep["ok"] = not rep["problems"]
    return rep


def main() -> None:
    print("=== Kira Doctor ===")
    rep = check(test_call=True)
    print(f"Default-Modell : {rep.get('default_model')}")
    print(f"Lokaler Fallback: {rep.get('local_fallback')}")
    print("\nRouting pro Task-Typ:")
    for tt, r in (rep.get("routing") or {}).items():
        print(f"  {tt:9s} -> {r['model']}  {'(Fallback lokal)' if r['fallback'] else '(CLOUD)'}")
    print("\nAPI-Keys:", ", ".join(f"{k}={'JA' if v else 'nein'}" for k, v in (rep.get("api_keys") or {}).items()))
    print(f"Ollama: {'ok' if rep.get('ollama') else 'FEHLT'} | node/npx: "
          f"{'ok' if rep.get('npx') else 'FEHLT'} | Disk frei: {rep.get('disk_free_gb')} GB "
          f"| state.db: {rep.get('db_mb')} MB")
    print("Imports:", ", ".join(f"{k}={'ok' if v else 'FEHLT'}" for k, v in (rep.get("imports") or {}).items()))
    tc = rep.get("test_call") or {}
    if "error" in tc:
        print(f"\nTest-Call: FEHLER — {tc['error']}")
    elif tc:
        print(f"\nTest-Call: {tc['where']} via {tc['model']} — {tc['latency_s']}s, ${tc['cost_usd']:.6f}")
        print(f"  Antwort: {tc['text']}")
    if rep["problems"]:
        print("\nPROBLEME:")
        for p in rep["problems"]:
            print(f"  - {p}")
    else:
        print("\nAlles gesund.")


if __name__ == "__main__":
    main()

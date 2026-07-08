# Kira auf dem Handy (PWA) — Einrichtung in 5 Minuten

Das Cockpit ist eine installierbare Web-App (PWA). Empfohlener Weg: **Tailscale Serve** —
dann kommen nur deine eigenen Geräte überhaupt an Kira ran (Schicht 1), HTTPS ist inklusive
(Voraussetzung fürs Installieren), und das **Zugangstoken** ist Schicht 2. Das Cockpit
lauscht weiter nur auf 127.0.0.1 — nichts wird ins offene Netz gestellt.

## Schritt 1 · Tailscale auf PC + Handy
1. [Tailscale](https://tailscale.com) auf dem PC installieren, mit demselben Konto am Handy
   (App aus dem Store) anmelden. Beide Geräte erscheinen im selben „Tailnet".
2. Auf dem PC (PowerShell): `tailscale serve --bg 8000`
   → Tailscale gibt eine `https://<pc-name>.<tailnet>.ts.net`-Adresse aus, die auf das
   Cockpit (Port 8000) zeigt. Läuft dauerhaft im Hintergrund (`--bg`).

## Schritt 2 · Fernzugriff in Kira aktivieren
Cockpit am PC → **⚙ Einstellungen → Zugänge → „📱 Fernzugriff aktivieren"**.
Das erzeugte Token wird angezeigt (nur direkt am PC sichtbar). Kopieren.

## Schritt 3 · Am Handy installieren
1. Die `https://….ts.net`-Adresse im Handy-Browser öffnen → Kira fragt nach dem Token →
   einfügen → Cockpit lädt (Cookie hält 180 Tage).
2. Browser-Menü → **„Zum Startbildschirm hinzufügen"** (Android/Chrome bietet „Installieren").
   Fertig — Kira liegt als App auf dem Homescreen, inklusive Chat, Live-Ops, Benchmarks.

## Sicherheit / Verhalten
- **Ohne aktivierten Fernzugriff ändert sich NICHTS** — Desktop, Wallpaper und alles Lokale
  laufen wie immer, kein Token nötig.
- Mit Fernzugriff: direkte Loopback-Anfragen bleiben frei (Desktop/Wallpaper), alles was über
  Proxy/Netz kommt (auch Tailscale Serve), braucht das Token — HTTP **und** WebSocket (Chat).
- Token neu würfeln: Fernzugriff aus- und wieder einschalten? Nein — ausschalten löscht das
  Token, das nächste Einschalten erzeugt ein frisches. Alte Handy-Cookies sind damit ungültig.
- Das Token liegt in `data/access_token.txt` (gitignored, bleibt auf dem PC).

## Störungsbilder
- „Token falsch" trotz richtigem Token → Fernzugriff war zwischendurch aus/an (neues Token),
  am Handy neu eingeben.
- Seite lädt gar nicht → `tailscale serve status` am PC prüfen; ist das Handy im Tailnet?
- PWA-Installation wird nicht angeboten → Adresse muss `https://` sein (Tailscale Serve macht
  das automatisch; nacktes `http://<ip>:8000` kann nicht installiert werden).

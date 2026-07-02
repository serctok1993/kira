"""Cockpit-UI, aus server.py extrahiert (S5.3a) — drei handliche Module statt
einer 90-KB-Wand: billiger fuer self_edit, sicherer gegen Truncation.
Zusammenbau bleibt EIN String; server.py exportiert ihn unveraendert weiter."""

from core.api.ui.css import HEAD_AND_CSS
from core.api.ui.views import VIEWS
from core.api.ui.script import SCRIPT

DASHBOARD_HTML = HEAD_AND_CSS + VIEWS + SCRIPT

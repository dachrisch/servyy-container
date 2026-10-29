# AGENTS.md — achim-hoefer

Statische Website der Praxis Höfer Architekten (Achim Höfer, München).
Ausgeliefert von `nginx:stable` auf `servy.lehel.xyz`, öffentlich unter
`höfer-architekten.de`.

## Aufbau

- `serve/` wird als Volume nach `/usr/share/nginx/html` gemountet.
- `serve/index.html` — die komplette Startseite, eine Datei mit inline CSS/JS.
- `serve/impressum.html` — Impressum, gleiche Gestaltungssprache.
- `serve/llms.txt`, `serve/robots.txt`, `serve/sitemap.xml` — Standarddateien für
  Crawler und LLMs. Neue Seiten gehören in `sitemap.xml` und `llms.txt`.
- `serve/public/og-image.png` — 1200×630 Social-Preview. Quelle: `og-image.html`
  im Service-Verzeichnis; im Browser bei exakt 1200×630 rendern und als PNG
  exportieren, dann in `serve/public/` ablegen.
- `serve/public/playground_assets/` — Favicon und die zwei vorhandenen
  Projektfotos (T-Systems, POST Bauen). Weitere Assets gibt es nicht.
- Kein Build-Schritt. Datei bearbeiten, committen, deployen.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.docker.achim-hoefer
```

## Fallstricke

- **Dateirechte:** Der nginx-Worker läuft als uid 101. `serve/` muss
  world-readable sein. Das erledigt die Rolle über
  `world_readable_paths: [serve]` in `ansible/plays/user.yml` — nicht manuell
  auf `660` setzen. Hintergrund: `history/2026-10-22_hofer-permissions-outage.md`.
- **Healthcheck:** Antwortet nginx mit 403/404, wird der Container unhealthy und
  Traefik zieht die Router ab — Besucher sehen die gebrandete 404. Bei
  „Seite weg“ zuerst Rechte und `docker ps` prüfen, nicht DNS.
- **Inhalte:** Die Referenzliste ist vollständig von der Altseite übernommen
  (7 Auftraggeber inkl. Unterpositionen). Nicht kürzen.
- **Beispielinhalte:** Mängelbericht („Feststellungen“) und Grundriss sind als
  beispielhafte Darstellung gekennzeichnet. Vor einem Livegang mit echten
  Begehungsdaten ersetzen oder entfernen.
- Ein früheres `update.sh` (TeleportHQ-Zip-Import) wurde am 2026-10-29 entfernt;
  es hätte die handgebaute Seite überschrieben.

## Gestaltung

- Plan-Set-Sprache: Zeichenraster, IBM Plex Mono + Inter Tight, Tinte `#0E1A25`,
  Orange `#CE5019`, Blau `#1D5B80`.
- Die Seite ist ein 1440 px breites „Blatt“ auf einem `#D3D5CE`-Tisch, Inhalt
  maximal 1280 px, ab 1440 px zentriert.
- Breakpoints: 1080 (Rail), 940 (Hero/Grundriss), 900 (Navigation),
  760 (Plankopf-Zeile), 560/420 (Mobile-Feinschliff).
- Interaktion: `Brandschutz-Ebene`-Toggle im Grundriss, `<details>` für
  Befund und Referenzen. Ohne JavaScript bleibt der Bestandsplan sichtbar.

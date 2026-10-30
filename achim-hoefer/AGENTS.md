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
- `serve/public/social-preview.png` — 1200×630 Social-Preview. Quelle: `og-image.html`
  im Service-Verzeichnis; im Browser bei exakt 1200×630 rendern und als PNG
  exportieren, dann in `serve/public/` ablegen. Bei inhaltlichen Änderungen den
  Dateinamen mitändern (`social-preview-2.png` o. ä.), weil Facebook & Co. das
  Bild sonst dauerhaft aus dem Cache zeigen.
- `serve/public/fonts/` — IBM Plex Mono 400/500/600 und Inter Tight 400–600
  (variable), jeweils **latin-Subset** als woff2. Quelle ist
  `fonts.googleapis.com/css2?family=…` mit Chrome-UA; die `src`-URLs aus der
  Antwort herunterladen. **Keine Google-Fonts-`<link>`-Tags einbauen** — die
  Schriften werden lokal ausgeliefert (DSGVO: LG München I, 3 O 17493/20) und
  über `@font-face` im `<style>` von `index.html` und `impressum.html`
  eingebunden. Neue Schnitte nur mit passendem `unicode-range` ergänzen.
- `serve/index.html` enthält am Ende des `<head>` ein JSON-LD-`@graph`
  (`ProfessionalService`, `Person`, `WebSite`). Adresse, Telefon, Kammer und
  Qualifikation darin müssen zum sichtbaren Inhalt passen — Google verwirft
  Markup, das nicht durch die Seite gedeckt ist.
- `serve/public/playground_assets/` — Favicon und die zwei vorhandenen
  Projektfotos (T-Systems, POST Bauen). Weitere Assets gibt es nicht.
- Kein Build-Schritt. Datei bearbeiten, committen, deployen.

## Deploy

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.repo.clone,user.docker.achim-hoefer
```

**`user.repo.clone` ist Pflicht.** Die Dateien kommen per `git pull` auf den
Server (`/home/cda/servyy-container/achim-hoefer/serve`). Ohne dieses Tag wird
nur das Compose-Projekt neu ausgerollt, der Checkout bleibt alt — der Lauf
meldet dann `changed=0` und die Live-Seite ändert sich nicht. Vor dem Deploy
muss der Commit auf `origin/master` liegen; nur lokal committet reicht nicht.

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
- **Barrierefreiheit/SEO:** Die Überschriften-Hierarchie muss lückenlos bleiben
  (kein Sprung h1 → h3), die Sprungmarke `.skip-link → #main` bleibt erstes
  fokussierbares Element, und jedes `<img>` braucht `width`/`height` plus
  `loading="lazy"` (die globale Regel `img{height:auto}` verhindert Verzerrung).
- **Zum `opencode-seo`-Linter:** Nicht als Maßstab nehmen, das Regelwerk ist
  auf englischsprachige Seiten gebaut. Auf dieser Seite dauerhaft falsch:
  `no-cta` und `no-cta-above-fold` (CTA-Erkennung sucht englische Stichwörter
  wie „get a quote"), `missing-trust-signals` (ebenso englisch),
  `missing-skip-link` (verlangt wörtlich „skip" im Linktext — ein korrektes
  deutsches Label kann das nie erfüllen) und `multiple-h1` (der Parser zählt
  einen Textknoten je Fundstelle, ein `<h1>` mit `<em>` gilt als mehrere).
  Brauchbar sind die strukturellen Regeln (`missing-jsonld`,
  `heading-order-skip`, `images-missing-alt`, `missing-meta-description`).
  Belastbarer Test für den Rest: im Browser nachzählen, nicht dem Score glauben.

## Gestaltung

- Plan-Set-Sprache: Zeichenraster, IBM Plex Mono + Inter Tight, Tinte `#0E1A25`,
  Orange `#CE5019`, Blau `#1D5B80`.
- Die Seite ist ein 1440 px breites „Blatt“ auf einem `#D3D5CE`-Tisch, Inhalt
  maximal 1280 px, ab 1440 px zentriert.
- Breakpoints: 1080 (Rail), 940 (Hero/Grundriss), 900 (Navigation),
  760 (Plankopf-Zeile), 560/420 (Mobile-Feinschliff).
- Interaktion: `Brandschutz-Ebene`-Toggle im Grundriss, `<details>` für
  Befund und Referenzen. Ohne JavaScript bleibt der Bestandsplan sichtbar.

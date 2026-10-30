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
  **Diese Dateien werden `immutable` für ein Jahr ausgeliefert** (siehe
  `nginx/default.conf`): wird ein Schnitt ersetzt, muss der Dateiname mit
  wechseln (`…-latin-2.woff2`), sonst sehen Bestandsbesucher ein Jahr lang die
  alte Datei.
  **Preload muss jeden Schnitt abdecken, der über dem Fold benutzt wird** —
  aktuell 400 und 500 der Mono plus Inter Tight. Fehlt einer, hängt er hinter
  dem HTML in der kritischen Kette (PSI: „Avoid chaining critical requests",
  ~80 ms). `mono-600` wird nur unterhalb des Folds gebraucht und bleibt bewusst
  ohne Preload.
- `nginx/default.conf` — ersetzt die Konfiguration des `nginx:stable`-Images und
  setzt `Cache-Control` (HTML revalidiert, Schriften ein Jahr `immutable`,
  `plan.css` eine Stunde, Bilder eine Woche, Crawler-Dateien eine Stunde) sowie
  gzip für CSS/JSON/SVG. Per Volume in `docker-compose.yml` gemountet. Vor
  Änderungen die Syntax gegen das echte Image prüfen:
  `docker run --rm -v "$PWD/nginx/default.conf":/etc/nginx/conf.d/default.conf:ro nginx:stable nginx -t`
- `serve/index.html` enthält am Ende des `<head>` ein JSON-LD-`@graph`
  (`ProfessionalService`, `Person`, `WebSite`). Adresse, Telefon, Kammer und
  Qualifikation darin müssen zum sichtbaren Inhalt passen — Google verwirft
  Markup, das nicht durch die Seite gedeckt ist.
- **Leistungsseiten:** `serve/brandschutzkonzept.html`,
  `serve/maengelbericht-brandschutz.html`,
  `serve/flucht-und-rettungsplaene.html`, `serve/wertermittlung.html`.
  Gemeinsames Stylesheet `serve/public/plan.css` (Pfade dort absolut:
  `/public/fonts/…`), Startseite bleibt eigenständig. Jede Seite trägt
  `Service` + `BreadcrumbList` + `FAQPage` als JSON-LD.
  **Quelle der vier Seiten ist `tools/gen_pages.py`** — Inhalte dort ändern und
  `cd achim-hoefer && python3 tools/gen_pages.py` laufen lassen, dann die
  erzeugten HTML-Dateien committen. Kein Build-Schritt beim Deploy; das Skript
  ist ein Werkzeug, damit FAQ-Text und `FAQPage`-Markup nicht auseinanderlaufen.
- **Gemeinsames Gerüst:** `.rail`, `.bar`, `.titleblock` und `.foot-nav` sind
  auf allen fünf Seiten **wortgleich**. Wer sie in `index.html` ändert, muss
  die Vorlage in `tools/gen_pages.py` mitziehen und `plan.css` angleichen —
  sonst laufen Startseite und Unterseiten optisch auseinander (genau das war
  beim ersten Anlauf passiert: Unterseiten reservierten den 56-px-Streifen der
  Rail, ohne sie zu rendern).
- **IndexNow:** `serve/<32-hex>.txt` enthält den IndexNow-Key. Der Dateiname
  *ist* der Key und muss unter `https://…/<key>.txt` erreichbar bleiben —
  Datei nicht löschen oder umbenennen.
- **Beispielbefund:** Der Befund im Hero ist als „Methodik · Beispielbefund"
  gekennzeichnet. Es gibt keine echten Begehungsdaten; die Karte zeigt die
  Methodik, nicht ein Projekt. Nicht wieder als konkreter Fall mit
  Berichtsnummer beschriften.
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
- **Zwei Orange-Töne:** `--orange` (`#CE5019`) für Linien, Rahmen, Pfeile und
  Flächen — als Nicht-Text braucht es nur 3:1. Für **kleine Schrift** dagegen
  `--orange-text` (`#B24414`): `#CE5019` erreicht auf Papier/Karte nur 3.6–3.8:1
  und fällt bei WCAG AA (4.5:1) durch. Gebänderte Kleinschrift auf dunklem Grund
  nicht unter `rgba(232,233,227,.58)` absenken, sonst kippt der Kontrast auf
  4.5:1. Prüfen mit Lighthouse (Accessibility muss 100 bleiben).
- Die Seite ist ein 1440 px breites „Blatt“ auf einem `#D3D5CE`-Tisch, Inhalt
  maximal 1280 px, ab 1440 px zentriert.
- Breakpoints: 1080 (Rail), 940 (Hero/Grundriss), 900 (Navigation),
  760 (Plankopf-Zeile), 560/420 (Mobile-Feinschliff).
- Interaktion: `Brandschutz-Ebene`-Toggle im Grundriss, `<details>` für
  Befund und Referenzen. Ohne JavaScript bleibt der Bestandsplan sichtbar.

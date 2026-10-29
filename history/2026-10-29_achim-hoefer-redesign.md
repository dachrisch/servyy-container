# achim-hoefer — Website-Redesign (Brandschutz-Fokus)

**Datum:** 2026-10-29
**Service:** `achim-hoefer` (nginx:stable auf `servy.lehel.xyz`)
**Domain:** `höfer-architekten.de`, `www.höfer-architekten.de`, `achim-hoefer.lehel.xyz`

## Zusammenfassung

Die TeleportHQ-Exportseite (Verdana 24 px, Orange `#fa8633`, „Logo“-Platzhalter
im Mobilmenü, englische Navigationslabels auf deutschem Text) ist durch eine
handgebaute Seite ersetzt, die den Brandschutz in den Mittelpunkt stellt:
Begehungsbefund und Brandschutz-Ebene als Beweis, vollständige Referenzen als
Beleg.

- `serve/index.html` neu — eine Datei, inline CSS/JS, keine Abhängigkeiten außer
  Google Fonts.
- `serve/impressum.html` neu — gleiche Gestaltungssprache, gleiche Rechtstexte
  (Anbieter, Kontakt, Berufsbezeichnung, Kammer).
- Entfernt: `serve/home.css`, `serve/style.css`, `serve/impressum.css`,
  `serve/package.json`, `achim-hoefer/update.sh` (TeleportHQ-Zip-Import, hätte
  die neue Seite überschrieben). `serve/public/` bleibt unverändert.

## Aufbau der Seite

1. **Hero** — „Brandschutz, der einer Begehung standhält.“ mit dem
   Feststellungs-Register (Klasse A/B, aufklappbare Empfehlungen) und drei
   Kennzahlen.
2. **Blatt 01 — Grundriss & Brandschutz-Ebene** — SVG-Grundriss mit
   umschaltbarer Ebene: Brandabschnitte, F30-Trennwände, Rauchabschnitt,
   Rettungswege.
3. **Blatt 02 — Leistungsverzeichnis** — Hochbau, Bauunterhalt, Brandschutz,
   Wertermittlung mit den Positionen der Altseite.
4. **Blatt 03 — Bestandsverzeichnis** — alle 7 Auftraggeber der Altseite, jeweils
   aufklappbar mit den vollständigen Unterpositionen (Epcos ×2, T-Systems ×4,
   POST inkl. Objekt- und Maßnahmenkatalog). Die zwei vorhandenen Projektfotos
   sind eingebunden, nicht ersetzt.
5. **Blatt 04 — Qualifikation**, **Blatt 05 — Kontakt** als Plankopf.
   Das Porträt von Achim Höfer steht in Blatt 04 („Wer prüft“), in Graustufen
   und mit mono Beschriftung, damit es zur Plan-Set-Sprache passt.
6. CTA an vier Stellen (Header, Hero, nach den Referenzen, Kontakt), überall
   `mailto:` mit vorbelegtem Betreff — kein Backend.

## Gestaltung

- Plan-Set-Sprache: Zeichenraster, IBM Plex Mono + Inter Tight, Tinte `#0E1A25`,
  Orange `#CE5019`, Blau `#1D5B80`.
- Seite als 1440-px-Blatt auf `#D3D5CE`, Inhalt max. 1280 px, ab 1440 px zentriert.
- Mobile: Rail und Plankopf-Zeile ausgeblendet, Navigation in der Leiste,
  CTA als „Anfrage“, Grundriss skaliert, Register und Referenzen stapeln.

## Beispielinhalte

Mängelbericht (`BE-2026-014`, vier Feststellungen) und Grundriss sind
schematisch. Beides ist auf der Seite als „Beispielhafte Darstellung“ bzw.
„Beispielgrundriss · keine Bestandsaufnahme“ gekennzeichnet. Vor einem
inhaltlichen Livegang mit echten Daten ersetzen — oder ersatzlos entfernen.

## Verifikation

- Lokal über `python3 -m http.server` im `serve/`-Verzeichnis: 200 für
  `index.html`, `impressum.html` und beide Projektfotos, keine 404 im Log,
  keine Konsolenfehler.
- Breiten 320/375/390/430/768/1024/1280/1440/1600/1980/2560/3440:
  `scrollWidth == clientWidth`, kein Element über den Viewport hinaus.
  Blattbreite ab 1600 px konstant 1440 px, zentriert.
- Toggle „Brandschutz-Ebene“ und die `<details>` in Befund/Referenzen geprüft
  (Desktop und 390 px).

## Deployment

```bash
cd ansible
./servyy.sh --limit servy.lehel.xyz --tags user.docker.achim-hoefer
```

Die Rolle setzt `serve/` über `world_readable_paths` auf lesbare Rechte für den
nginx-Worker (uid 101). Ohne das antwortet nginx mit 403, der Container wird
unhealthy und Traefik zieht die Router ab.

## Offene Punkte

- [ ] Echte Begehungsfotos/-befunde für das Register (oder Register entfernen).
- [ ] Projektfotos liegen nur in 300 px Breite vor — für Retina wären größere
      Aufnahmen nötig.
- [ ] Impressum: „Aufsichtsbehörde“ heißt jetzt „Zuständige Kammer“; Inhalt
      unverändert übernommen, rechtlich gegenlesen lassen.

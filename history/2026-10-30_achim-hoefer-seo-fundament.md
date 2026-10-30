# ADR: SEO- und Barrierefreiheits-Fundament für achim-hoefer

**Datum:** 2026-10-30
**Status:** Accepted
**Service:** `achim-hoefer` (nginx:stable auf `servy.lehel.xyz`)
**Domain:** `höfer-architekten.de` (`xn--hfer-architekten-mwb.de`)

## Kontext

Die Seite ist seit dem Redesign vom 2026-10-29 (`history/2026-10-29_achim-hoefer-redesign.md`)
live. Vor dem Aufbau von Sichtbarkeit (Google Search Console, Google
Business Profile, Landingpages je Leistung) fehlten die technischen
Grundlagen, die Google und Screenreader erwarten:

- kein strukturiertes Datenmarkup (kein JSON-LD) — damit keine Chance auf
  Knowledge Panel, Rich Results oder eine saubere Entität „Höfer Architekten“
- Schriften von `fonts.googleapis.com` geladen: zwei zusätzliche
  DNS-/TLS-Verbindungen vor dem ersten Textaufbau (LCP) und eine
  datenschutzrechtliche Angriffsfläche — für ein Münchner Büro relevant, weil
  das LG München I (3 O 17493/20) die Einbindung von Google Fonts ohne
  Einwilligung als rechtswidrig bewertet hat
- `<h1>` gefolgt von `<h3>` (Sprung in der Hierarchie)
- kein Skip-Link
- Bilder ohne `width`/`height` und ohne `loading` — Layout-Sprünge beim Laden

## Entscheidung

Sechs Änderungen an `serve/index.html` und `serve/impressum.html`, ohne
Build-Schritt und ohne Änderung der Gestaltung:

1. **JSON-LD** als `@graph` mit `ProfessionalService`, `Person` und `WebSite`.
   Nur Daten, die auf der Seite sichtbar sind (Adresse Karolinenstraße 9,
   Telefon, Bayerische Architektenkammer, EIPOS/TU Dresden). Bewusst **nicht**
   aufgenommen: `geo`-Koordinaten, `openingHours`, `priceRange`, `sameAs` —
   diese Angaben liegen nicht vor und würden geraten.
2. **Schriften lokal** — IBM Plex Mono 400/500/600 und Inter Tight 400–600
   (variable) als woff2, latin-Subset, 4 Dateien / 80 KB in
   `serve/public/fonts/`, eingebunden über `@font-face` im Inline-`<style>`.
   Die Google-`<link>`-Tags und beide `preconnect`-Hinweise sind entfernt.
3. **Preload** der zwei wichtigsten Schnitte.
4. **Skip-Link** `.skip-link → #main`, erstes fokussierbares Element, per
   `position:fixed` erst bei `:focus` sichtbar.
5. **Überschriften-Hierarchie** repariert: „Feststellungen aus der Begehung“
   von `<h3>` auf `<h2 class="bef-title">`, Selektor von `.bef-head h3` auf
   `.bef-head .bef-title` umgestellt — Typografie unverändert (11.5 px / 500).
6. **Bilder** mit `width`/`height` (echte Maße: 300×163, 300×227, 500×761),
   `loading="lazy"`, `decoding="async"`; global `img{height:auto}` ergänzt,
   damit die Attribut-Höhe die Proportionen nicht verzerrt.

## Konsequenzen

### Positiv

- ✅ Null Drittanbieter-Requests: die Seite lädt nur noch vom eigenen Host
  (im Netzwerk-Mitschnitt verifiziert: 4 Requests, alle `127.0.0.1`)
- ✅ DSGVO-Risiko durch Google-Fonts-Einbindung entfällt
- ✅ Kein Render-Blocking durch fremdes CSS mehr
- ✅ Maschinenlesbare Entität für Name, Adresse, Telefon, Leistungen, Person
- ✅ Überschriften-Hierarchie und Skip-Link entsprechen WCAG 2.4.1 / 1.3.1
- ✅ Bilder reservieren ihren Platz (CLS-Anteil der Bilder ≈ 0)

### Negativ / Tradeoffs

- ⚠️ 80 KB Schriften liegen jetzt im Repo statt bei Google — bei neuen
  Schnitten muss `serve/public/fonts/` mitgepflegt werden
- ⚠️ Nur latin-Subset: Zeichen außerhalb (z. B. Kyrillisch) fallen auf
  Systemschriften zurück
- ⚠️ JSON-LD ist handgepflegt — bei Adress-/Telefonänderung muss es
  mitgeändert werden, sonst weicht es vom sichtbaren Inhalt ab

### Implementierungsdetails

**Geänderte Dateien:**
- `achim-hoefer/serve/index.html` (MODIFY) — JSON-LD, `@font-face`, Preload,
  Skip-Link, h2, Bildattribute, `img{height:auto}`
- `achim-hoefer/serve/impressum.html` (MODIFY) — `@font-face`, Google-Tags raus
- `achim-hoefer/serve/public/fonts/` (NEW) — 4 woff2-Dateien
- `achim-hoefer/AGENTS.md` (MODIFY) — Fonts, JSON-LD, A11y-Regeln, Linter-Hinweis

**Verifikation:**
- ✅ JSON-LD parst als valides JSON (beide Seiten)
- ✅ Überschriftenfolge `index` `[1,2,2,2,3,3,3,3,2,2,2,3]`, `impressum`
  `[1,2,2,2,2]` — keine Sprünge, je genau ein `<h1>`
- ✅ Alle `@font-face`-Dateien existieren; im Browser geladen:
  IBM Plex Mono 400/500, Inter Tight 400–600 (600 lädt erst bei Bedarf)
- ✅ Netzwerk: nur 4 Requests, keine `fonts.googleapis`/`gstatic`
- ✅ Responsiv 320–3440 px: `scrollWidth == clientWidth` in allen zwölf
  Breiten, Blattbreite ab 1600 px konstant 1440 px
- ✅ Bild-Proportionen: Abweichung Attribut↔natürlich ≤ 0.009 (keine Verzerrung)
- ✅ Screenshot 1280 px und 390 px gegen den Stand vor der Änderung geprüft:
  Darstellung identisch

**Key Learnings:**

1. **`height:auto` ist Pflicht.** `width`/`height`-Attribute werden vom Browser
   als Präsentationshinweis in eine feste Höhe übersetzt. Mit `width:100%` aus
   CSS und ohne `height:auto` wird das Bild verzerrt. Chrome DevTools meldet
   danach trotzdem „Lazy-loaded images should have explicit dimensions“ für
   Bilder ohne `aspect-ratio` in CSS — ein Fehlalarm, wenn die Attribute
   gesetzt sind; die CLS-Messung ist der belastbare Test.
2. **Der SEO-Linter taugt hier nur teilweise.** Das `opencode-seo`-Regelwerk
   erkennt CTAs und Trust-Signale über englische Stichwortlisten; „Begehung
   anfragen" und „Kammer" matchen nicht, deshalb melden `no-cta` und
   `missing-trust-signals` falsch und die Punktzahl fällt auf 0/100. Auch
   `missing-skip-link` lässt sich auf einer deutschen Seite nicht erfüllen: die
   Regel verlangt wörtlich „skip" im Linktext. Und der Parser zählt ein `<h1>`
   mit Inline-Markup als mehrere H1 (ein Textknoten je Fundstelle). Brauchbar
   waren die strukturellen Regeln: fehlendes JSON-LD, Heading-Sprung,
   fehlende Meta-Description. Nach dem Fix steht der Score bei 4/100, obwohl
   die geforderten Dinge im DOM vorhanden sind — im Browser gegengeprüft.
3. **Bilder im `public/` sind WebP mit `.jpg`/`.png`-Namen.** `bauen-300w.jpg`
   und `t-systems-200h.jpg` sind WebP (300×227 und 300×163), ebenso
   `hoefer-1500w.png`. nginx liefert sie mit falschem `Content-Type` aus;
   Browser erkennen das Format und stellen korrekt dar, sauber ist es nicht.

### Bekannte Einschränkungen

- Projektfotos liegen nur in 300 px Breite vor (schon im Redesign vermerkt) —
  für Retina zu klein, unverändert offen
- Mängelbericht und Grundriss sind weiterhin als beispielhaft gekennzeichnet
- `sameAs` im JSON-LD bleibt leer, bis es echte Profile (Google Business,
  LinkedIn o. ä.) gibt

## Alternativen erwogen

### Alt A: Google Fonts behalten, nur `preload` ergänzen
Einfacher, kein Repo-Wachstum. Verworfen: lässt zwei Fremd-Verbindungen vor
dem ersten Pixel und die DSGVO-Frage offen.

### Alt B: Auf Systemschriften umstellen
Schnellste Variante, null Bytes. Verworfen: die Plan-Set-Sprache lebt von IBM
Plex Mono und Inter Tight; das Redesign würde sichtbar verlieren.

### Alt C: Umfangreiches Schema (Artikel, Breadcrumbs, FAQ, Produkte)
Höhere Linter-Punktzahl. Verworfen: Eine einseitige Praxis-Website hat keine
Artikel und keine Breadcrumb-Navigation. Markup ohne Entsprechung im Inhalt
ist ein Risiko, keine Optimierung.

### Alt D: Commercial-SEO-Suite (Ahrefs/Semrush/Seobility) als Messlatte
Verworfen für den jetzigen Schritt: Zwei URLs rechtfertigen kein Abo. Erst
Search Console und Business Profile, dann entscheiden.

## Verwandte Entscheidungen

- `history/2026-10-29_achim-hoefer-redesign.md` — das Redesign, dessen
  offener Punkt „größere Projektfotos" hier unberührt bleibt
- `history/2026-10-22_hoefer-permissions-outage.md` — Dateirechte in `serve/`

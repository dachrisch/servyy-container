# ADR: Leistungsseiten, www-Redirect und IndexNow für achim-hoefer

**Datum:** 2026-10-30
**Status:** Accepted
**Service:** `achim-hoefer` (nginx:stable auf `servy.lehel.xyz`)
**Domain:** `höfer-architekten.de` (`xn--hfer-architekten-mwb.de`)
**Setzt auf:** `2026-10-30_achim-hoefer-seo-fundament.md`

## Kontext

Nach dem technischen Fundament (JSON-LD, lokale Schriften, Überschriften,
Skip-Link) und dem Deploy stand die Seite bei Google mit **einer** Inhaltsseite
da. Ein Betrieb, der sieben Leistungen verkauft, war auf genau eine Landingpage
reduziert — für Suchanfragen wie „Brandschutzkonzept München" oder
„Mängelbericht Brandschutz" gab es keine Seite, auf der die Anfrage landet.

Drei weitere Punkte aus der Bestandsaufnahme:

- `www.` und der Apex lieferten **byte-identischen Inhalt** (beide 200); nur das
  Canonical unterschied sie.
- Der Hero enthielt einen **frei erfundenen Mängelbericht** mit Berichtsnummer
  `BE-2026-014`, Objekt und Datum. Auf der Seite einer echten Praxis ist das
  eine Scheinreferenz — es liegen keine echten Begehungsdaten vor.
- Kein Pfad, auf dem Änderungen zeitnah an Bing und Yandex gehen.

## Entscheidung

**1. Vier Leistungsseiten** — `brandschutzkonzept.html`,
`maengelbericht-brandschutz.html`, `flucht-und-rettungsplaene.html`,
`wertermittlung.html`. Je Seite: eigenes `<title>`/Description in den
Anzeigegrenzen, `Service` + `BreadcrumbList` + `FAQPage` als JSON-LD,
FAQ-Block, Querverweise auf die drei Schwester­seiten.

**2. Gemeinsames Stylesheet** `serve/public/plan.css` statt kopiertem Inline-CSS.
Die Startseite bleibt eigenständig (eine Datei, kein Build-Schritt) — sie wurde
nur um den Block `.spec-links` erweitert, der auf die vier Seiten verlinkt.

**3. Hero-Befund umgewidmet:** „BE-2026-014 · Bürogebäude · München" →
„Methodik · Beispielbefund", „4 offen" → „4 Beispiele", Überschrift
„So sieht ein Befund aus", Fußzeile „Beispielhafte Darstellung · keine
Bestandsaufnahme". Die Gestaltung bleibt, die Scheinreferenz ist weg.

**4. www → Apex** über einen eigenen Traefik-Router mit `redirectregex`
(permanent). Der `_prod`-Router beansprucht nur noch den Apex.

**5. IndexNow** — Key `694f5aa9118e447f9e74d6c3d9887df7` als
`serve/<key>.txt`, Submission aller sechs URLs an `api.indexnow.org`.

## Konsequenzen

### Positiv

- ✅ Vier indexierbare Seiten mit eigenständigen Suchintentionen statt einer
- ✅ Interne Verlinkung mit sprechenden Ankertexten in beide Richtungen
- ✅ Ein `www.`-Host weniger: 308 auf den Apex, Pfad und Query bleiben erhalten
- ✅ Keine Scheinreferenz mehr auf der Seite einer echten Praxis
- ✅ Änderungen erreichen Bing/Yandex ohne Warten auf einen Crawl
- ✅ Sehr leicht: 6 Requests, 75 KB, CLS 0, TTFB 94 ms (gemessen live)

### Negativ / Tradeoffs

- ⚠️ `plan.css` dupliziert die Design-Tokens der Startseite — zwei Stellen bei
  einer Farb-/Schriftänderung
- ⚠️ FAQ-Text steht doppelt (sichtbar + JSON-LD); Konsistenz ist Handarbeit
- ⚠️ Beim Container-Restart liefert Traefik für ~30 s die 404-Fehlerseite, bis
  der Healthcheck greift. Kein Regressionsfall, aber sichtbar.
- ⚠️ `FAQPage`-Rich-Results vergibt Google seit 2023 nur noch an Behörden- und
  Gesundheitsseiten; das Markup bleibt gültig und hilft der Auszeichnung, aber
  es ist kein Rich-Result-Versprechen

### Implementierungsdetails

**Geänderte/neue Dateien:**
- `serve/{brandschutzkonzept,maengelbericht-brandschutz,flucht-und-rettungsplaene,wertermittlung}.html` (NEW)
- `serve/public/plan.css` (NEW)
- `serve/694f5aa9118e447f9e74d6c3d9887df7.txt` (NEW, IndexNow-Key)
- `serve/index.html` (MODIFY — Hero-Befund, `.spec-links`, CSS)
- `serve/sitemap.xml` (MODIFY — 2 → 6 URLs)
- `serve/llms.txt` (MODIFY — vier Seiten ergänzt)
- `docker-compose.yml` (MODIFY — www-Router + redirectregex)
- `AGENTS.md` (MODIFY)

**Commits:** `2eb5824` (Inhalt + Routing), davor `ca5f972` (Deploy-Befehl)

**Verifikation (live):**
- ✅ Apex, Impressum und alle vier Leistungsseiten: 200
- ✅ `www` → 308 auf Apex, `/wertermittlung.html?x=1` → Pfad/Query erhalten
- ✅ `sitemap.xml` listet 6 URLs, alle 200
- ✅ IndexNow: `202 Accepted` für 6 URLs
- ✅ Lokal: kein gebrochener interner Link, je genau ein `<h1>`, keine
  Heading-Sprünge, JSON-LD valide, FAQ sichtbar == FAQ-Schema (4–5 Fragen)
- ✅ Mobil 390×844 (echte Emulation): `scrollWidth == clientWidth`, Innenabstand
  16 px beidseitig, Navigation ausgeblendet, CTA sichtbar

**Key Learnings:**

1. **`.sheet` + `.wrap` kollidieren.** `<section class="sheet wrap">` — `.wrap`
   setzt `padding:0 var(--pad)`, `.sheet` setzt später `padding:<v> 0 <v>` und
   überschreibt damit den Innenabstand komplett (gleiche Spezifität, spätere
   Regel gewinnt). Auf der Startseite fällt das wegen der 56 px Rail kaum auf,
   auf den Unterseiten im Mobil-Layout sofort. Lösung: `.sheet` nur noch
   `padding-block`.
2. **`www`-Redirect über Traefik:** Der Redirect-Router braucht trotzdem ein
   Backend (`services.<name>.loadbalancer.server.port`), sonst ist der Router
   ungültig. Referenzen als `…@docker` schreiben, wenn Middleware und Service
   im selben Provider liegen.
3. **Deploy ist zweistufig.** Der `user.repo.clone`-Task holt den Commit auf den
   Server; ohne ihn rollt nur Compose neu aus. Der dokumentierte Befehl in
   `AGENTS.md` fehlte genau dieses Tag (siehe `ca5f972`).
4. **Restart-Fenster:** Nach dem Ausrollen ist die Seite für ~30 s 404, bis der
   Healthcheck healthy meldet. Beim Prüfen direkt nach dem Deploy nicht
   erschrecken — erst `docker ps` fragen.

### Bekannte Einschränkungen

- Projektfotos nur in 300 px Breite vorhanden (keine größeren Originale)
- Keine echten Begehungsdaten: Der Beispielbefund bleibt Methodik
- British-Englisch/Deutsch-Mischung im Linter-Score unverändert irrelevant
- LCP live nicht gemessen: das Lighthouse-Fenster muss im Vordergrund sein

## Alternativen erwogen

### Alt A: Inline-CSS je Unterseite kopieren
Kein zusätzliches Asset, Dateien bleiben autark. Verworfen: vier Kopien von
Design-Tokens, die bei der nächsten Farbänderung auseinanderlaufen.

### Alt B: Startseite auf `plan.css` umstellen
Eine Quelle für alle Seiten. Verworfen für diesen Schritt: die Startseite ist
gerade frisch verifiziert; ein CSS-Refactor dort ist ein eigenes Risiko ohne
Nutzen für die Sichtbarkeit. Kandidat für später.

### Alt C: Erfundenen Befund ersatzlos entfernen
Sauberste inhaltliche Lösung. Verworfen, weil der Hero damit seine visuelle
Mitte verliert und keine echten Daten zum Ersetzen vorliegen — die Umwidmung
zur Methodik erreicht dasselbe Ziel ohne Designverlust.

### Alt D: Flucht- und Rettungspläne in die Brandschutzseite integrieren
Weniger Seiten, weniger Pflege. Verworfen: „Flucht- und Rettungsplan" ist eine
eigene Suchanfrage mit eigener Intention.

## Verwandte Entscheidungen

- `2026-10-30_achim-hoefer-seo-fundament.md` — JSON-LD, Schriften, A11y
- `2026-10-29_achim-hoefer-redesign.md` — Gestaltungssprache, die hier
  weitergeführt wird

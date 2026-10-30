# ADR: Cache-Control für achim-hoefer

**Datum:** 2026-10-30
**Status:** Accepted
**Service:** `achim-hoefer`
**Setzt auf:** `2026-10-30_achim-hoefer-seo-fundament.md`

## Kontext

PageSpeed Insights meldete `Performance: 100` mit FCP/LCP/Speed Index je 1.1 s,
TBT 0 ms und CLS 0 — aber zwei offene Hinweise:

- **Use efficient cache lifetimes** — *Est savings of 64 KiB*
- **Document request latency** — *Est savings of 43 KiB*

nginx lieferte bis dahin nur `ETag` und `Last-Modified`, aber kein
`Cache-Control`. Browser cachen dann heuristisch (typisch 10 % der Zeit seit
`Last-Modified`) und revalidieren bei jedem Wiederbesuch. Die 64 KiB sind genau
die vier woff2-Dateien plus `plan.css`.

Der zweite Hinweis war ein Fehlalarm: TTFB wurde mit 94 ms gemessen, es gibt
kein Latenzproblem.

## Entscheidung

Eine eigene nginx-Konfiguration, per Volume über die des Images gemountet
(`nginx/default.conf` → `/etc/nginx/conf.d/default.conf`), mit Lebensdauern nach
Änderungshäufigkeit:

| Pfad | Cache-Control | Begründung |
|---|---|---|
| `*.html`, `/` | `max-age=0, must-revalidate` | Ein Deploy soll sofort greifen; 304 über ETag kostet nur einen Roundtrip |
| `/public/fonts/` | `max-age=31536000, immutable` | Ändert sich nur, wenn ein Schnitt ausgetauscht wird |
| `/public/plan.css` | `max-age=3600` | Ändert sich mit dem Design |
| `/public/` (Bilder) | `max-age=604800` | Selten, aber nicht nie |
| `robots.txt`, `sitemap.xml`, `llms.txt`, IndexNow-Key | `max-age=3600` | Ändern sich bei neuen Seiten |
| `/` (Fallback) | `max-age=0, must-revalidate` | Sicherheitsnetz |

Zusätzlich `gzip` für CSS, JSON, XML und SVG — das Image komprimiert von Haus
aus nur `text/html`.

Bewusst **nicht** enthalten: `immutable` für `plan.css`. Das wäre der Fehler
gewesen — die Datei ändert sich bei jeder Design-Anpassung, und Besucher hätten
ein Jahr lang die alte Version. `immutable` gilt nur dort, wo der Dateiname bei
Änderung mitwechselt.

## Konsequenzen

### Positiv

- ✅ Wiederbesuche laden Schriften und CSS nicht erneut (die 64 KiB entfallen)
- ✅ HTML bleibt sofort aktualisierbar — kein „Cache leeren" nach einem Deploy
- ✅ gzip für CSS/SVG/JSON ergänzt
- ✅ Keine neue Abhängigkeit, kein Build-Schritt: eine Datei plus ein Volume

### Negativ / Tradeoffs

- ⚠️ **Neue Regel für Menschen:** Schriften sind `immutable`. Wer einen Schnitt
  ersetzt, ohne den Dateinamen zu ändern, liefert Bestandsbesuchern ein Jahr
  lang die alte Datei. In `AGENTS.md` dokumentiert.
- ⚠️ Ein Fehler in dieser Datei verhindert den Containerstart → nginx
  unhealthy → Traefik zieht die Router ab. Deshalb: Syntax vorher gegen das
  echte Image prüfen, nicht nach dem Deploy.
- ⚠️ Zwei Konfigurationsorte für Header (nginx für Cache, Traefik für HSTS und
  Security-Header). Nicht offensichtlich, aber bewusst getrennt: Traefik kann
  keine pfadabhängigen Cache-Regeln.

### Implementierungsdetails

**Geänderte/neue Dateien:**
- `nginx/default.conf` (NEW)
- `docker-compose.yml` (MODIFY — zusätzliches Volume)
- `AGENTS.md` (MODIFY)

**Verifikation:**
- ✅ `nginx -t` gegen `nginx:stable` auf dem Server: *configuration file syntax
  is ok* — vor dem Deploy, nicht danach
- ✅ Wegwerfcontainer auf Port 8899 gegen den echten `serve/`-Checkout: jede der
  neun Pfadklassen liefert den erwarteten `Cache-Control`-Wert, Healthcheck
  `-A healthcheck -I /` gibt 200, `Content-Encoding: gzip` auf `plan.css`
- ✅ Erst nach diesen beiden Prüfungen committet und ausgerollt

**Key Learnings:**

1. **`immutable` ist eine Falle, wenn der Dateiname stabil bleibt.** Der Reflex
   „statische Dateien ein Jahr cachen" ist bei unversionierten URLs falsch.
   Richtig ist: `immutable` nur für Dateien, die beim Ändern umbenannt werden.
2. **Konfiguration gegen das echte Image prüfen.** Kein lokal installiertes
   nginx, aber `docker run --rm -v …:ro nginx:stable nginx -t` auf dem Server
   beantwortet die Frage vor dem Deploy statt danach.
3. **Wegwerfcontainer als Staging.** Eine zweite Instanz auf einem freien Port,
   gegen denselben `serve/`-Checkout, prüft Verhalten (Header, Status, gzip)
   ohne das Productive-Container anzufassen.
4. **`add_header` vererbt nicht.** Sobald eine `location` ein eigenes
   `add_header` setzt, gilt das auf Server-Ebene nicht mehr für sie — deshalb
   steht `Cache-Control` in jeder Location einzeln.

### Bekannte Einschränkungen

- Der `Document request latency`-Hinweis in PSI bleibt, obwohl TTFB 94 ms
  beträgt — ein Fehlalarm der Heuristik, nicht behebbar und nicht nötig
- CrUX-Felddaten fehlen weiterhin; die Seite ist zu neu für echte
  Nutzermessungen

## Alternativen erwogen

### Alt A: Traefik-Router auf `PathPrefix('/public/')` mit headers-Middleware
Nur Labels, keine neue Datei. Verworfen: pfadabhängige Cache-Regeln werden in
Traefik unübersichtlich (ein Router plus Middleware je Pfadklasse), und für
diese Seite gehört die Auslieferung ohnehin zu nginx.

### Alt B: Alles unter `/public/` ein Jahr `immutable`
Einfachste Regel. Verworfen wegen `plan.css` — es hätte Designänderungen für
Bestandsbesucher ein Jahr lang unsichtbar gemacht.

### Alt C: Nichts tun, Score ist ohnehin 100
Vertretbar. Verworfen, weil die 64 KiB ein echter, messbarer Punkt waren und die
Änderung klein ist. Der Performance-Score bleibt davon unberührt — es geht um
Wiederbesuche.

## Verwandte Entscheidungen

- `2026-10-30_achim-hoefer-kontrast-fix.md` — Lighthouse-Audit derselben Seite
- `2026-10-30_achim-hoefer-seo-fundament.md` — lokale Schriften, die hier
  überhaupt erst zum Cache-Thema wurden

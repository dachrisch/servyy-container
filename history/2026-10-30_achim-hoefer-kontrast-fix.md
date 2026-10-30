# ADR: Kontrast von Kleinschrift auf achim-hoefer

**Datum:** 2026-10-30
**Status:** Accepted
**Service:** `achim-hoefer`
**Setzt auf:** `2026-10-30_achim-hoefer-seo-fundament.md`

## Kontext

Lighthouse (Google) meldete auf der Startseite `Accessibility: 96`, ein
einziger fehlgeschlagener Audit: `color-contrast`, 19 Knoten. Betroffen waren
ausschliesslich kleine Beschriftungen — 8.5 bis 9 px, also weit unter der
Schwelle, ab der WCAG AA eine niedrigere Anforderung zuliesse (grosse Schrift
beginnt erst bei 24 px bzw. 18.66 px fett). Eine Schriftvergrösserung hätte das
Problem also nicht gelöst, der Kontrast musste geändert werden.

Die vier Ursachen:

| Element | Farbe | Verhältnis |
|---|---|---|
| `.bef-count`, `.flag.a` (Klasse A/B) | `#CE5019` auf `#EFF0EA` | 3.83:1 |
| `.legend .flag.a` (auf Papier `#E8E9E3`) | `#CE5019` auf `#E8E9E3` | 3.59:1 |
| `details.bef .txt small` (`--ink-2` bei `.75`) | effektiv `#6A747A` | 4.17:1 |
| `.strip-in .m`, `.pk .m` (Papier bei `.5`) | effektiv `#7B8284` auf `#0E1A25` | 4.50:1 |

## Entscheidung

Zwei neue Werte statt einer Palette-Änderung:

1. **`--orange-text: #B24414`** — dieselbe Orange-Familie, aber als *Textfarbe*
   tauglich: 4.91:1 auf der Karte, 4.61:1 auf Papier. Verwendet in
   `.bef-count`, `.legend .flag.a`, `details.bef .flag.a`.
   `--orange` (`#CE5019`) bleibt unverändert für Rahmen, Pfeile, Linien und
   Flächen — als Nicht-Text genügen dort 3:1.
2. **Deckkraft der gedämpften Beschriftungen angehoben**, statt eine neue
   Farbe einzuführen: `.txt small` von `opacity:.75` auf `.85` (5.37:1),
   `.strip-in .m` und `.pk .m` von `rgba(...,.5)` auf `rgba(...,.58)` (5.51:1).

## Konsequenzen

### Positiv

- ✅ Accessibility 96 → **100**, 19 fehlerhafte Knoten → 0, 36 Audits bestanden
- ✅ Optisch praktisch unverändert — bei der Abnahme war kein Unterschied zu
  sehen, was der Anspruch war
- ✅ Markenfarbe bleibt erhalten; nur die Textvariante ist dunkler
- ✅ Die vier Leistungsseiten waren bereits bei 100 und brauchten keine Änderung

### Negativ / Tradeoffs

- ⚠️ Zwei Orange-Töne im CSS — ohne die Notiz in `AGENTS.md` legt jemand
  irgendwann wieder `var(--orange)` auf kleinen Text
- ⚠️ Die Deckkraft-Lösung ist implizit: der effektive Farbwert steht nirgends,
  er ergibt sich aus Alpha über Hintergrund. Bei einem Hintergrundwechsel muss
  der Kontrast neu geprüft werden.

### Implementierungsdetails

**Geänderte Dateien:** `serve/index.html` (Variable + 6 Deklarationen),
`AGENTS.md`

**Verifikation:**
- ✅ Lighthouse mobile snapshot vorher/nachher: 96 → 100, 0 Failed Audits
- ✅ Vorher/Nachher-Bildausschnitte aller drei Komponenten verglichen
- ✅ W3C-Validator und schema.org-Validator unberührt (nur CSS geändert)

**Key Learnings:**

1. **Der erste Anlauf reichte nicht.** Nach drei Korrekturen stand es immer
   noch bei 96 — der Plankopf im Kontaktbereich nutzt eine *eigene* Regel
   `.pk .m` mit demselben `.5`-Alpha und stellte die restlichen 8 Knoten.
   Sichtprüfung findet das nicht, nur ein erneuter Audit-Lauf.
2. **Kontrast ist nicht mit Schriftgrösse zu lösen.** Die Reflexe „Schrift
   grösser machen" hilft bei WCAG AA nicht, weil die 4.5:1-Schwelle bis 24 px
   gilt. Es führt kein Weg an einer dunkleren Textfarbe vorbei.
3. **`4.50` ist nicht bestanden.** Die Stripe-/Plankopf-Labels lagen exakt auf
   4.50:1 und wurden als 4.49 gerundet abgelehnt. Bei derartigen Grenzwerten
   immer einen Puffer einplanen.

### Bekannte Einschränkungen

- Performance weiterhin nicht gemessen: Lighthouse im Navigationsmodus
  verlangt ein Fenster im Vordergrund (`NO_FCP`), und die PageSpeed-API des
  Projekts ist im Tageskontingent erschöpft (429).

## Alternativen erwogen

### Alt A: `--orange` global auf `#B24414` umstellen
Eine Variable, überall konsistent. Verworfen: würde auch Rahmen, Pfeile und
Flächen abdunkeln und damit die Gestaltung sichtbar verändern — genau das, was
vermieden werden sollte.

### Alt B: Schriftgrössen anheben
Kein Eingriff in die Farbe. Verworfen, weil wirkungslos: unter 24 px gilt
weiterhin 4.5:1, und grössere Beschriftungen hätten das Layout der Plan-Set-
Sprache verschoben.

### Alt C: Kontrastfehler ignorieren
Der Audit betrifft nur Kleinstschrift. Verworfen: Accessibility ist ein
Ranking- und Vertrauensfaktor, und die Behebung kostete sieben Deklarationen.

## Verwandte Entscheidungen

- `2026-10-30_achim-hoefer-seo-fundament.md` — Skip-Link, Überschriften, Markup
- `2026-10-30_achim-hoefer-leistungsseiten.md` — die vier Unterseiten

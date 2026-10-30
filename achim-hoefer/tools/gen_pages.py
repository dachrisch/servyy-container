#!/usr/bin/env python3
"""Generate the four service pages for achim-hoefer/serve.

Dev tool, not a build step: the site is served as plain static HTML. Run it
after editing content here, then commit the regenerated pages.

    cd achim-hoefer && python3 tools/gen_pages.py


FAQ text and FAQPage JSON-LD are emitted from the same Python data, so the
markup can never contradict the visible copy.
"""
import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "serve"
BASE = "https://xn--hfer-architekten-mwb.de"
BIZ = f"{BASE}/#business"
MAIL = "mailto:achim.hoefer@gmx.net"
PHONE_DISPLAY = "0171 9727560"

PAGES = [
    {
        "slug": "brandschutzkonzept.html",
        "title": "Brandschutzkonzept München — Höfer Architekten",
        "desc": "Brandschutzkonzepte für Neubau, Umbau und Nutzungsänderung in München: Schutzzieldefinition, Maßnahmen, Alternativen, Abstimmung mit Behörde und Feuerwehr.",
        "kicker": "Leistung 01 · Brandschutz",
        "h1": 'Brandschutzkonzept für Bestand und <em>Neubau</em>',
        "lead": "<b>Ein Brandschutzkonzept legt fest, wie ein Gebäude seine Schutzziele erreicht</b> — Personenschutz, Begrenzung der Brandausbreitung, wirksame Löschmaßnahmen und Rettungswege. Es beschreibt die Maßnahmen im Zusammenspiel, nicht als Liste von Einzelvorgaben, und wird bei Abweichungen von den Vorgaben der Bauordnung zum zentralen Nachweisdokument.",
        "sections": [
            ("Wann ein Konzept gebraucht wird", """
<p>Für einfache Gebäude genügt in der Regel ein Brandschutznachweis nach Schema. Ein Konzept wird gebraucht, sobald das Vorhaben von den Standardannahmen abweicht — also bei Sonderbauten, bei Bestand mit gewachsener Struktur, wenn Nutzungen wechseln, oder wenn ein Bauherr etwas möchte, was die Verordnung so nicht vorsieht.</p>
<ul>
<li><b>Neubau von Sonderbauten</b> — Schulen, Kindertagesstätten, Versammlungsstätten, Verkaufsstätten, Hochhäuser und Gebäude besonderer Art und Nutzung.</li>
<li><b>Umbau und Sanierung im Bestand</b> — wenn die vorhandene Struktur die Standardlösung nicht zulässt.</li>
<li><b>Nutzungsänderung</b> — der häufigste Fall: ein Lager wird zum Büro, ein Wohnhaus zum Kindergarten. Die bauliche Substanz bleibt, die Schutzziele ändern sich.</li>
<li><b>Abweichungen und Kompensationen</b> — wenn eine Anforderung nicht eingehalten werden kann, braucht es ein gleichwertiges Schutzniveau statt einer Ausnahme.</li>
</ul>"""),
            ("Was ein Konzept enthält", """
<p>Ein Konzept ist kein Formular. Es beginnt bei der Risikobewertung und endet bei der Maßnahme, die auf der Baustelle tatsächlich umgesetzt werden kann.</p>
<h3>Bestandsaufnahme und Schutzziele</h3>
<p>Gebäudestruktur, Nutzung, Personenanzahl, Rettungswegsituation und Brandabschnitte werden aufgenommen. Daraus werden die konkreten Schutzziele für dieses Gebäude abgeleitet — nicht aus dem Schema, sondern aus Gebäude und Nutzung.</p>
<h3>Maßnahmen im Zusammenhang</h3>
<p>Baulicher, anlagentechnischer und organisatorischer Brandschutz werden im Zusammenhang bewertet: Feuerwiderstand von Bauteilen, Brandabschnitte und Rauchabschnitte, Rettungswege und deren Länge, Sicherheitsbeleuchtung, Anlagentechnik, Kennzeichnung und Räumung.</p>
<h3>Nachweis, Dokumentation, Abstimmung</h3>
<p>Nachweise werden so aufgebaut, dass Behörde und Feuerwehr sie prüfen können. Abweichungen werden begründet und mit einer gleichwertigen Lösung hinterlegt. Die Abstimmung mit der Brandschutzdienststelle gehört dazu — nicht als Schlusspunkt, sondern begleitend.</p>"""),
            ("Grundlagen", """
<p>Maßgebend sind in Bayern die <b>Bayerische Bauordnung (BayBO)</b> mit den eingeführten technischen Baubestimmungen, die <b>Muster-Richtlinie über brandschutztechnische Anforderungen an Leitungsanlagen (MLAR)</b> sowie die anerkannten Regeln der Technik, insbesondere die Normenreihe <b>DIN 4102</b>. Bei Anlagen, die immissionsschutzrechtlich genehmigt werden, kommt das <b>BImSchG</b>-Verfahren hinzu.</p>
<p>Die Sonderbaurichtlinie bildet den Rahmen für Gebäude mit erhöhten Anforderungen; davon abweichende Lösungen sind genau der Bereich, in dem ein Konzept die Spielräume auslotet.</p>"""),
            ("Ablauf", """
<ol>
<li><b>Erstgespräch und Unterlagen</b> — Pläne, Nutzungsbeschreibung, Bestand an Nachweisen. Daraus wird der tatsächliche Aufwand eingeschätzt.</li>
<li><b>Begehung</b> — bei Bestandsobjekten unverzichtbar. Zeichnungen und Wirklichkeit weichen ab, oft genau an den Stellen, auf die es ankommt.</li>
<li><b>Konzept und Maßnahmenkatalog</b> — Schutzziele, Maßnahmen, Prioritäten, Alternativen mit ihren Folgen.</li>
<li><b>Abstimmung</b> — mit Bauherr, Fachplanern und Brandschutzdienststelle.</li>
<li><b>Einreichung und Begleitung</b> — Fassung für das Verfahren, Nachreichungen, Rückfragen bis zur Entscheidung.</li>
</ol>"""),
        ],
        "faq": [
            ("Ab wann brauche ich ein Brandschutzkonzept statt eines Nachweises?",
             "Ein Nachweis reicht bei Gebäuden, die den Standardlösungen der Bauordnung folgen. Sobald das Vorhaben davon abweicht — Sonderbau, Nutzungsänderung, Bestand mit ungewöhnlicher Struktur oder eine gewünschte Abweichung — braucht es ein Konzept, weil das Zusammenspiel der Maßnahmen bewertet werden muss statt einzelner Punkte."),
            ("Ist eine Nutzungsänderung ohne Baumaßnahme genehmigungspflichtig?",
             "Häufig ja. Ändert sich die Nutzung, ändern sich in der Regel auch die brandschutzrechtlichen Anforderungen, selbst wenn kein Stein bewegt wird. Ein Lager mit anderen Personenanzahlen oder Fluchtwegen ist ein anderer Fall als ein Büro. Das lässt sich vorab klären, bevor Bauantrag oder Betrieb gestoppt werden."),
            ("Was kostet ein Brandschutzkonzept?",
             "Das hängt von Gebäudegröße, Nutzung, Bestandslage und dem Umfang der Abstimmung ab. Pauschale Zahlen sind unseriös, weil zwei Gebäude gleicher Größe einen völlig unterschiedlichen Prüfaufwand machen können. Nach Erstgespräch und Sichtung der Unterlagen lässt sich der Aufwand belastbar eingrenzen."),
            ("Werden bestehende Brandschutznachweise anerkannt?",
             "Wenn sie zum Vorhaben und zu den aktuell geltenden Anforderungen passen, ja. Ältere Nachweise beziehen sich oft auf eine frühere Nutzung oder eine andere Rechtslage. Geprüft wird, was davon tragfähig bleibt und wo nachgeführt werden muss."),
            ("Besteht ein Anspruch auf eine Abweichung?",
             "Nein. Eine Abweichung ist keine Ausnahme, die man beantragt und bewilligt bekommt, sondern ein Vorschlag mit Begründung, dass das Schutzniveau auf andere Weise erreicht wird. Wie tragfähig der ist, entscheidet sich an der Sache — deshalb wird er im Konzept begründet und nicht nur behauptet."),
        ],
    },
    {
        "slug": "maengelbericht-brandschutz.html",
        "title": "Mängelbericht Brandschutz München — Höfer Architekten",
        "desc": "Bestandsbegehung und Mängelbericht Brandschutz in München: Feststellungen mit Klasse A/B, Fotos, Priorisierung und Empfehlungen statt anonymer Prüfliste.",
        "kicker": "Leistung 02 · Bestand",
        "h1": 'Begehung und <em>Mängelbericht</em> im Bestand',
        "lead": "<b>Eine Brandschutzbegehung prüft, was tatsächlich in Gebäude steht, nicht was in den Plänen steht.</b> Ergebnis ist ein Bericht mit Feststellungen, einer Einordnung nach Handlungsbedarf, Fotos und konkreten Empfehlungen — ein Dokument, mit dem sich Eigentümer, Betreiber und Versicherung auseinandersetzen können.",
        "sections": [
            ("Wann eine Begehung sinnvoll ist", """
<p>Der Anlass ist selten ein Genehmigungsverfahren. Meistens geht es um Haftung, Versicherung oder die Frage, was als Nächstes saniert werden muss.</p>
<ul>
<li><b>Vor Übernahme eines Bestandsgebäudes</b> — zu wissen, was brandschutzseitig noch offen ist, gehört in die Kaufentscheidung.</li>
<li><b>Nach Jahren ohne Prüfung</b> — Nutzungen ändern sich schleichend, Türen und Rettungswege werden zugestellt, Kennzeichnungen verblassen.</li>
<li><b>Vor der Versicherung</b> — Schäden werden reguliert, aber Vorsorgepflichten sind nachzuweisen.</li>
<li><b>Nach einer baulichen Änderung</b> — zu prüfen, ob der Bestand darunter gelitten hat.</li>
<li><b>Bei mehreren Standorten</b> — um Maßnahmen zu priorisieren, statt überall gleichzeitig anzufangen.</li>
</ul>"""),
            ("Was festgestellt wird", """
<p>Die Begehung folgt dem Weg, den ein Mensch im Brandfall nimmt, und dann dem Weg des Feuers.</p>
<h3>Rettungswege und Fluchtmöglichkeiten</h3>
<p>Länge und Verlauf von Fluchtwegen, Hindernisse, Aufstellflächen, offen gehaltene Türen, zweiter Rettungsweg.</p>
<h3>Baulicher Brandschutz</h3>
<p>Feuerwiderstand von Trennwänden, Durchdringungen und Abschottungen, Brand‑ und Rauchabschnitte, Zustand der Bauteile.</p>
<h3>Betrieblicher Brandschutz</h3>
<p>Kennzeichnung, Sicherheitsbeleuchtung, Flucht- und Rettungspläne, Feuerlöscher, Zugänglichkeit für die Feuerwehr, Lagerung.</p>"""),
            ("Klasse A und Klasse B", """
<p>Jede Feststellung wird eingeordnet, damit aus einer Liste von Beobachtungen eine Reihenfolge des Handelns wird.</p>
<ul>
<li><b>Klasse A</b> — unmittelbarer Handlungsbedarf. Punkte, bei denen der Schuld eines Schutzziels nicht erreicht wird und die auch kurzfristig behoben werden können.</li>
<li><b>Klasse B</b> — Feststellungen, die im Rahmen der Bauunterhaltung mitlaufen: Kennzeichnung, Abschottung im Zuge einer anstehenden Maßnahme, Dokumentation.</li>
</ul>
<p>Die Einordnung ist das eigentliche Ergebnis. Ein Bericht, der dreißig Punkte gleich gewichtet auflistet, wird nicht umgesetzt.</p>"""),
            ("Was Sie bekommen", """
<ul>
<li>Eine <b>Feststellungsliste</b> mit laufender Nummer, Ort, Bild, Beschreibung und Empfehlung.</li>
<li>Eine <b>Priorisierung</b> nach Klasse A und B sowie als Vorschlag für die Reihenfolge.</li>
<li><b>Fotos</b> der betroffenen Stellen — wichtig für Budgetgespräche und die Nachverfolgung.</li>
<li>Ein kurzes <b>Erläuterungsblatt</b>, warum eine Feststellung ein Mangel ist: die Rechts- oder Normgrundlage, nicht das Bauchgefühl.</li>
</ul>
<p>Eine Warnung zur Verständlichkeit: Der Bericht ist eine fachliche Bestandsaufnahme und kein Sanierungskonzept. Für die Umsetzung braucht es Umfang, Kosten und Termine — das ist ein zweiter Schritt.</p>"""),
            ("Ablauf", """
<ol>
<li><b>Auftragsklärung</b> — Ziel, Gebäudeteile, gewünschte Detailschärfe. Ein Pilotenstandort statt aller Standorte zuerst.</li>
<li><b>Begehung</b> — vor Ort, mit Zugang zu allen relevanten Bereichen, Termin mit dem Betreiber.</li>
<li><b>Bericht</b> — Feststellungen, Klassen, Fotos, Erläuterung.</li>
<li><b>Nachgespräch</b> — offene Punkte, Priorisierung mit dem Betreiber, Schnittstelle zu Brandschutzkonzept oder Bauunterhalt.</li>
</ol>"""),
        ],
        "faq": [
            ("Ist eine Brandschutzbegehung gesetzlich vorgeschrieben?",
             "Es gibt keine allgemeine Prüfpflicht, die jeden Eigentümer in festem Turnus trifft. Für Betreiber und Arbeitgeber ergeben sich Pflichten aus Arbeitsschutz- und Bauordnungsrecht, für Sonderbauten kommen Prüfturnen hinzu. Der praktische Nutzen liegt dort, wo Haftung, Versicherung oder anstehende Investitionen betroffen sind."),
            ("Was kostet eine Begehung?",
             "Der Preis hängt von Gebäudegröße, Anzahl der Standorte und dem gewünschten Detailgrad ab — eine Halle ist ein anderer Fall als ein Verwaltungsgebäude mit verteilten Nebengebäuden. Nach Auftragsklärung ist der Aufwand kalkulierbar."),
            ("Was passiert mit dem Bericht?",
             "Er gehört dem Auftraggeber. Er ist kein Behördendokument und wird nicht eingereicht, solange der Auftraggeber es nicht will — er ist die eigene Bestandsaufnahme, nicht ein Verstoß gegen etwas."),
            ("Besteht bei zu spät gemeldeten Mängeln Haftung?",
             "Das ist eine juristische Frage, keine brandschutztechnische, und wird hier nicht beantwortet. Die Durchsicht selbst schafft jedenfalls Tatsachen, auf die sich Haftung gründen lässt — deshalb ist die Dokumentation so aufgebaut, dass sie nachvollziehbar bleibt."),
            ("Kann eine Begehung auch ohne Zugang zu allen Bereichen stattfinden?",
             "Ja, dann ist der Bericht entsprechend eingeschränkt. Nicht begangene Bereiche und nicht prüfbare Punkte sind im Bericht ausgewiesen — eine lückenhafte Begehung, die als vollständig ausgegeben wird, wäre wertlos."),
        ],
    },
    {
        "slug": "flucht-und-rettungsplaene.html",
        "title": "Flucht- und Rettungspläne München — Höfer Architekten",
        "desc": "Flucht- und Rettungspläne München: Erstellung nach DIN ISO 23601, Aktualisierung nach Umbau, Prüfung vorhandener Pläne.",
        "kicker": "Leistung 03 · Kennzeichnung",
        "h1": 'Flucht- und <em>Rettungspläne</em>',
        "lead": "<b>Ein Flucht- und Rettungsplan zeigt einer Person, die das Gebäude nicht kennt, wie sie im Brandfall schnell nach draußen kommt.</b> Das klingt einfach und scheitert in der Praxis an Plänen, die einen Zustand von vor drei Umbauten zeigen, oder an Stellen hängen, an denen niemand sie findet.",
        "sections": [
            ("Das eigentliche Problem ist nicht der Plan, sondern die Aktualität", """
<p>Pläne veralten, ohne dass es jemand merkt: Wände kommen hinzu, Flure werden Büro, Türen erhalten Beschläge, Sicherheitsbeleuchtung wird versetzt, Abteilungen ziehen um. Der Plan bleibt im Rahmen und wird Teil des Baustellenbildes. Nach einigen Zyklen prüft man einen Plan gegen ein Gebäude, und es passt nicht mehr.</p>
<p>Deshalb beginnt jede Erstellung mit dem Ist-Zustand — Begehung und Prüfung des Plans gegen das Gebäude, nicht gegen archivierte Baueingabepläne.</p>"""),
            ("Wann die Pläne zu prüfen sind", """
<ul>
<li><b>Nach jedem Umbau</b>, auch wenn keine Nutzungsänderung genehmigt wurde — der Anlass ist die Baumaßnahme, nicht das Verfahren.</li>
<li><b>Nach einem Nutzungswechsel</b> in Teilbereichen, mit anderer Belegung und anderen Wegen.</li>
<li><b>Nach einem Umzug oder geänderten Flächen</b> — hier weichen Pläne am häufigsten ab.</li>
<li><b>Bei unregelmäßiger Prüfung</b> als Bestandsaufnahme, wenn kein aktueller Plan nachweisbar ist.</li>
<li><b>Nach Änderung der Anlagentechnik</b>, wenn Sicherheitsbeleuchtung oder Leittechnik betroffen sind.</li>
</ul>"""),
            ("Was ein Plan leisten muss", """
<p>Ein Flucht- und Rettungsplan nach <b>DIN ISO 23601</b> ist ein genormtes Dokument, kein Schaubild. Er enthält den aktuellen Grundriss des jeweiligen Bereichs, den eigenen Standort, die Fluchtwege und Notausgänge, Sammelplätze sowie die Rettungs- und Brandschutzeinrichtungen.</p>
<h3>Die drei Sätze, die zählen</h3>
<p>Erstens: Die Symbole sind genormt, nicht frei gewählt — <b>DIN 4844-2</b>. Zweitens: Der Standort ist exakt und eindeutig. Drittens: Der Plan hängt dort, wo er bei eingeschränkter Sicht wirkt — im Augenhöhenbereich, an Wegen, an denen Menschen vorbeikommen.</p>
<p>Auf der Arbeitsschutzseite greift die <b>ASR A2.3</b> für Fluchtwege und Notausgänge, in Sicherheitskennzeichnungsfragen die <b>DIN EN ISO 7010</b>. Bei Sonderbauten kommen die Vorgaben der Sonderbaurichtlinie und der jeweiligen Versammlungsstätten- oder Schulbauvorschrift hinzu.</p>"""),
            ("Ablauf", """
<ol>
<li><b>Begehung</b> — Bereich für Bereich, mit Aufnahme der tatsächlichen Wege und Ausgänge.</li>
<li><b>Planaufbau</b> — Grundriss und Eintragung nach Norm, abgestimmt auf den Aushangort.</li>
<li><b>Abstimmung</b> — mit Betreiber, Sicherheitsbeauftragtem, bei Sonderbauten mit der Brandschutzdienststelle.</li>
<li><b>Druck und Aushang</b> — für nicht-laminierte Nutzung dauerhaft lesbar; mit Hinweis auf Prüfdatum.</li>
<li><b>Nachführung</b> — anlassbezogen nach jeder Änderung, statt bei Bedarf.</li>
</ol>"""),
        ],
        "faq": [
            ("Gibt es eine Prüfpflicht für Flucht- und Rettungspläne?",
             "Es gibt keine bundesweit einheitliche Prüffrist. Betreiber und Arbeitgeber sind über Arbeitsschutzrecht verpflichtet, den Plan auf dem Stand der Dinge zu halten; für Sonderbauten ergeben sich Turnusfragen aus den jeweiligen Vorschriften. Der praktische Anlass ist meist ein Umbau oder ein Nutzungswechsel."),
            ("Was kostet ein Flucht- und Rettungsplan?",
             "Das hängt von Anzahl der Bereiche, Gebäudekomplexität und der Frage ab, ob vorhandene Grundrissdaten brauchbar sind. Einzelne Bereiche sind schnell gemacht; die Kosten entstehen bei Bestandsaufnahme und Abstimmung, nicht beim Druck."),
            ("Reicht es, den Plan nach einem Umbau elektronisch zu aktualisieren?",
             "Ein aktualisierter Plan, der noch im Rahmen hängt und einen alten Stand zeigt, ist eine falsche Tatsache. Wenn die Änderung sichtbar ist, muss der Aushang mit; das gehört in den Ablauf der Baumaßnahme und nicht in ein späteres Aufräumen."),
            ("Können bestehende Pläne übernommen werden?",
             "Wenn Aufbau, Symbole und Schriftbild der Norm entsprechen und der Inhalt noch stimmt, ja. Ältere Pläne entsprechen häufig einer früheren Normgeneration; dann ist eine Neufassung sauberer als eine Korrektur."),
        ],
    },
    {
        "slug": "wertermittlung.html",
        "title": "Wertermittlung Grundstücke München — Höfer Architekten",
        "desc": "Verkehrswertermittlung bebauter und unbebauter Grundstücke in München nach ImmoWertV: Vergleichs-, Ertrags- und Sachwertverfahren.",
        "kicker": "Leistung 04 · Wert",
        "h1": 'Wertermittlung bebauter und <em>unbebauter</em> Grundstücke',
        "lead": "<b>Eine Wertermittlung macht den Wert eines Grundstücks nachvollziehbar, statt in eine Zahl zu münden, die man glauben muss.</b> Sie ist dann belastbar, wenn Verfahren, Datengrundlage und die Grenzen der Aussage offenliegen — als Argument, dem Eigentümer, Gutachterausschuss und Finanzverwaltung folgen können.",
        "sections": [
            ("Anlässe", """
<p>Ein Wert wird selten für sich gebraucht. Er wird gebraucht, weil eine Entscheidung davon abhängt.</p>
<ul>
<li><b>Kauf und Verkauf</b> — als Grundlage für Preisverhandlung, nicht als Preis.</li>
<li><b>Erbauseinandersetzung und Übertragung</b> — wenn mehrere Parteien die Zahl nachvollziehen können müssen.</li>
<li><b>Steuerliche Bewertung</b> — wenn die Finanzverwaltung eine Zahl vertreten muss.</li>
<li><b>Bilanzierung und Finanzierung</b> — als Gutachten mit Verfahren und Datengrundlage.</li>
<li><b>Schadensfälle</b> — wenn der Zustand nach einem Ereignis zu bewerten ist.</li>
<li><b>Sanierungs- und Investitionsentscheidungen</b> — wenn ein Mehraufwand gegen einen Wertvorteil zu stellen ist.</li>
</ul>"""),
            ("Drei Verfahren — die Wahl ist Teil des Ergebnisses", """
<p>Die <b>Immobilienwertermittlungsverordnung (ImmoWertV)</b> gibt die anerkannten Verfahren vor. Welches passt, hängt vom Objekt ab; die falsche Wahl produziert eine Zahl, die formal richtig und inhaltlich falsch ist.</p>
<h3>Vergleichswertverfahren</h3>
<p>Baut auf Kaufpreisen vergleichbarer Grundstücke. Das richtige Verfahren für unbebaute Grundstücke und Eigentumswohnungen, wo genügend Vergleichsfälle vorliegen. Schwierig, wenn der Markt dünn ist — was in Teilen Münchens durchaus vorkommt.</p>
<h3>Ertragswertverfahren</h3>
<p>Setzt den erzielbaren Ertrag einer Immobilie ins Verhältnis zu einem Liegenschaftszinssatz. Das Verfahren für Mietobjekte und Renditeimmobilien: Der Wert ist der Wert der Erträge, nicht der Wert des Betons.</p>
<h3>Sachwertverfahren</h3>
<p>Herstellungskosten minus Alterswertminderung, plus Bodenwert. Anwendbar bei eigengenutzten und Sonderimmobilien, für die weder Vergleichsfälle noch Erträge tragfähig sind — und dort, wo Baugestalt und Ausstattung den Wert bestimmen.</p>"""),
            ("Was eine belastbare Bewertung enthält", """
<ul>
<li><b>Objektbeschreibung</b> mit Baujahr, Zustand, Grundstück, Ausstattung, eventuell bestehenden Wertermittlungen.</li>
<li><b>Datengrundlage</b> — Bodenrichtwerte, Vergleichsfälle, Liegenschaftszinssätze, Mietdaten, Herstellungskosten; als Teil des Gutachtens, nicht als Anhang.</li>
<li><b>Verfahren und Ableitung</b>, nachvollziehbar gerechnet, mit ausgewiesenen Annahmen.</li>
<li><b>Markt- und Zustandsanpassungen</b> mit Begründung.</li>
<li><b>Grenzen der Aussage</b> — was nicht geprüft wurde und wie stark die Zahl davon abhängt.</li>
</ul>
<p>Der letzte Punkt wird in der Praxis am häufigsten weggelassen. Wer ihn auslässt, verkauft eine Scheingenauigkeit.</p>"""),
        ],
        "faq": [
            ("Worin unterscheidet sich ein Sachverständigengutachten vom Gutachterausschuss?",
             "Der Gutachterausschuss ist die amtliche Stelle, die für Grundstückswerte in Bayern Vergleichsfälle und Bodenrichtwerte führt und auf Antrag Gutachten erstattet. Ein privates Gutachten ist eine eigenständige Bewertung, die sich auf dieselben Daten stützen kann — und deren Argumentation man in Verhandlungen verwenden kann, ohne an ein Verfahren gebunden zu sein."),
            ("Welches Verfahren ist für meine Immobilie das richtige?",
             "Das hängt vom Objekt ab: Vergleichswert bei unbebauten Grundstücken und Wohnungseigentum mit ausreichenden Vergleichsfällen, Ertragswert bei Mietobjekten, Sachwert bei eigengenutzten und Sonderimmobilien. Die Wahl wird im Gutachten begründet, weil sie das Ergebnis wesentlich bestimmt."),
            ("Was kostet eine Wertermittlung?",
             "Der Aufwand hängt von Objekt, Verfahren und der Frage ab, welche Daten vorliegen. Bei einem einfachen unbebauten Grundstück ist der Aufwand ein anderer als bei einem Industrieobjekt mit mehreren Bauabschnitten. Nach Sichtung der Unterlagen ist der Umfang eingrenzbar."),
            ("Wie aktuell muss eine Wertermittlung sein?",
             "Für eine Entscheidung sollte sie den Markt zum Entscheidungszeitpunkt abbilden. Ältere Bewertungen können als Ausgangspunkt dienen, aber ein Gutachten von vor Jahren ist keine Grundlage für eine aktuelle Preisfindung — Immobilienmärkte und Zinssätze ändern sich schneller als die Gebäude."),
        ],
    },
]

RELATED = {
    "brandschutzkonzept.html": ("Brandschutzkonzept", "Neubau und Bestand"),
    "maengelbericht-brandschutz.html": ("Begehung und Mängelbericht", "Bestand"),
    "flucht-und-rettungsplaene.html": ("Flucht- und Rettungspläne", "Kennzeichnung"),
    "wertermittlung.html": ("Wertermittlung", "Wert"),
}

NAV_CTA = f"""<a class="cta" href="{MAIL}?subject=Projektanfrage">
          <span class="cta-l">Projekt anfragen</span><span class="cta-s">Anfrage</span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
        </a>"""


def render(page):
    slug = page["slug"]
    url = f"{BASE}/{slug}"
    crumb = RELATED[slug][0]

    def esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    faq_html = "\n".join(
        f"""        <details>
          <summary>{esc(q)}</summary>
          <div class="answer"><p>{esc(a)}</p></div>
        </details>""" for q, a in page["faq"]
    )

    sections_html = "\n".join(
        f'          <h2>{h}</h2>\n{body.strip()}' for h, body in page["sections"]
    )

    related = "\n".join(
        f'            <li><a href="{s}">{label} <span>{sub}</span></a></li>'
        for s, (label, sub) in RELATED.items() if s != slug
    )

    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Service",
                "@id": f"{url}#service",
                "name": crumb,
                "serviceType": crumb,
                "url": url,
                "provider": {"@id": BIZ},
                "areaServed": {"@type": "City", "name": "München"},
                "description": page["desc"],
            },
            {
                "@type": "BreadcrumbList",
                "@id": f"{url}#breadcrumb",
                "itemListElement": [
                    {"@type": "ListItem", "position": 1, "name": "Startseite", "item": f"{BASE}/"},
                    {"@type": "ListItem", "position": 2, "name": crumb, "item": url},
                ],
            },
            {
                "@type": "FAQPage",
                "@id": f"{url}#faq",
                "mainEntity": [
                    {"@type": "Question", "name": q,
                     "acceptedAnswer": {"@type": "Answer", "text": a}}
                    for q, a in page["faq"]
                ],
            },
        ],
    }

    return f"""<!doctype html>
<html lang="de">
<head>
<title>{page["title"]}</title>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="description" content="{page["desc"]}" />
<link rel="canonical" href="{url}" />
<meta property="og:type" content="website" />
<meta property="og:locale" content="de_DE" />
<meta property="og:site_name" content="Höfer Architekten" />
<meta property="og:title" content="{page["title"]}" />
<meta property="og:description" content="{page["desc"]}" />
<meta property="og:url" content="{url}" />
<meta property="og:image" content="{BASE}/public/social-preview.png" />
<meta property="og:image:type" content="image/png" />
<meta property="og:image:width" content="1200" />
<meta property="og:image:height" content="630" />
<meta property="og:image:alt" content="Höfer Architekten — Brandschutz, der einer Begehung standhält." />
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{page["title"]}" />
<meta name="twitter:description" content="{page["desc"]}" />
<meta name="twitter:image" content="{BASE}/public/social-preview.png" />
<meta name="theme-color" content="#E8E9E3" />
<link rel="icon" href="/public/playground_assets/favicon-32x32.png" type="image/png" sizes="32x32" />
<link rel="preload" href="/public/fonts/inter-tight-400-600-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="preload" href="/public/fonts/ibm-plex-mono-500-latin.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="/public/plan.css" />
<script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False, indent=2)}
</script>
</head>
<body>

<a class="skip-link" href="#main">Zum Inhalt springen</a>

<div class="shell">

  <aside class="rail" aria-hidden="true">
    <span class="tick"></span>
    <span class="vert">Höfer Architekten · München</span>
    <span class="num">2026</span>
  </aside>

  <header>
    <div class="bar">
      <a class="brand" href="/">Höfer Architekten</a>
      <nav>
        <a href="/#grundriss">01 Grundriss</a>
        <a href="/#leistungen">02 Leistungen</a>
        <a href="/#referenzen">03 Referenzen</a>
        <a href="/#qualifikation">04 Qualifikation</a>
        <a href="/#kontakt">05 Kontakt</a>
      </nav>
      {NAV_CTA}
    </div>
    <div class="titleblock">
      <div class="tb-grid">
        <div class="tb-cell"><span class="m">Büro</span><b>Höfer Architekten</b></div>
        <div class="tb-cell"><span class="m">Leistungen</span><b>Architektur · Brandschutz · Wertermittlung</b></div>
        <div class="tb-cell"><span class="m">Ort</span><b>München</b></div>
        <div class="tb-cell"><span class="m">Telefon</span><b><a href="tel:+491719727560">0171 9727560</a></b></div>
      </div>
    </div>
  </header>

  <nav class="crumb" aria-label="Brotkrümelnavigation">
    <a href="/">Startseite</a><span class="sep">/</span><span>{crumb}</span>
  </nav>

  <main id="main">
    <section class="sheet wrap">
      <span class="kicker">{page["kicker"]}</span>
      <h1 class="page-title">{page["h1"]}</h1>
      <p class="lead">{page["lead"]}</p>

      <div class="prose">
{sections_html}

          <h2>Häufige Fragen</h2>
          <div class="faq">
{faq_html}
          </div>
      </div>

      <div class="cta-band">
        <div>
          <span class="m">Kontakt</span>
          <p>Kurze Beschreibung des Vorhabens genügt — Adresse, Nutzung und der Anlass reichen für eine erste Einschätzung.</p>
        </div>
        <a class="btn" href="{MAIL}?subject=Projektanfrage">
          Projekt anfragen
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
        </a>
      </div>

      <div class="related">
        <span class="m">Weitere Leistungen</span>
        <ul>
{related}
        </ul>
      </div>
    </section>
  </main>

  <footer>
    <div class="wrap">
      <div class="foot-nav">
        <span class="m">Leistungen</span>
        <a href="/brandschutzkonzept.html">Brandschutzkonzept</a>
        <a href="/maengelbericht-brandschutz.html">Begehung &amp; Mängelbericht</a>
        <a href="/flucht-und-rettungsplaene.html">Flucht- &amp; Rettungspläne</a>
        <a href="/wertermittlung.html">Wertermittlung</a>
      </div>
      <div class="foot">
        <span>© Höfer Architekten 2026</span>
        <a href="/impressum.html">Impressum</a>
        <span class="sp">Karolinenstraße 9 · 80538 München</span>
      </div>
    </div>
  </footer>

</div>

</body>
</html>
"""


for p in PAGES:
    path = OUT / p["slug"]
    path.write_text(render(p), encoding="utf-8")
    print(f"wrote {p['slug']:34s} {len(path.read_text(encoding='utf-8')):>7,} bytes  "
          f"{len(p['faq'])} FAQ")

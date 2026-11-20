# dbaccess: INSERT und DELETE pro Antrag

**Date:** 2026-11-20
**Status:** in Umsetzung (Infra-Rolle vor dem App-Rollout).

| Repo | Change | PR |
|---|---|---|
| `leaguesphere` | `may_insert`/`may_delete` am Antrag, Checkboxen, Anzeige in Queue/Detail/Entscheidung, Events, `tick.sh`-Grant | [#2494](https://github.com/dachrisch/leaguesphere/pull/2494) |
| `servyy-container` | Provisioner erhält `DELETE`; Kommentare und Runbook an die tatsächliche Grant-Option angepasst | [dieser PR] |

## Problem

Ein dbaccess-Konto bekam `SELECT` auf die Allow-List und `SELECT, UPDATE` auf die
beantragten Tabellen. `INSERT` war technisch vergebbar, wurde aber nie vergeben; `DELETE`
konnte der Provisioner selbst nicht weitergeben. Gleichzeitig las sich die Hilfe wie
„Schreiben“, was die Erwartung „INSERT geht auch“ erzeugte.

Die App konnte das nicht allein lösen: `DELETE` fehlte in
`ansible/plays/roles/ls_dbeaver_access/tasks/provisioner.yml`, und MariaDB führt die
Grant-Option **pro Datenbank**, nicht pro Privileg. Der Provisioner konnte daher schon
vorher INSERT (und CREATE) weitergeben, obwohl der Kommentar das Gegenteil behauptete.

## Änderung

* Der Provisioner hält jetzt `SELECT, INSERT, UPDATE, DELETE` auf dem Anwendungsschema,
  die Datenrechte in einer Anweisung `WITH GRANT OPTION`; `CREATE` bleibt eine separate
  Anweisung ohne Option. Die Rolle kann damit weiterhin keinen DDL-Zugriff an ein
  Temp-Konto geben.
* Die Kommentare in `provisioner.yml` beschreiben die Grant-Option korrekt als
  datenbankweit: dieselbe Option deckt SELECT, INSERT, UPDATE und DELETE ab.
* `docs/leaguesphere-temp-db-access.md` nennt die neue Fähigkeit in Ablauf,
  Fähigkeitstabelle, Regeln und Provisioner-Abschnitt. `INSERT`/`DELETE` gelten nur für
  die beantragten Tabellen, nur nach ausdrücklichem Haken und nur nach Freigabe;
  neu eingefügte Zeilen stehen nicht in der Sicherungskopie, `DELETE` ist nur über
  `bak_<table>_<date>` (manuelles `INSERT … SELECT`) rückgängig zu machen.
* Reihenfolge: erst diese Rolle, dann das LeagueSphere-Release. Ein Tick, der DELETE
  vergibt, bevor der Provisioner es hält, würde den Antrag als `failed` parken (mit
  genau dieser Begründung) statt ein halbes Konto zu hinterlassen.

## Verification

* `yamllint -c .yamllint.yml ansible/plays/roles/ls_dbeaver_access`
* `ansible-playbook servyy.yml --syntax-check -i testing`
* Nach dem Rollout: `SHOW GRANTS` für den Provisioner zeigt
  `GRANT SELECT, INSERT, UPDATE, DELETE ON <db>.* … WITH GRANT OPTION`.
* Ein Test-Antrag mit INSERT+DELETE auf einer harmlosen Tabelle: Konto zeigt
  `SELECT, INSERT, UPDATE, DELETE` nur auf dieser Tabelle, die Read-Tabellen nur
  `SELECT`, die Sicherungskopie existiert, und die Events nennen die Rechte-Menge.

## Rollout

1. Diese Rolle auf `servyy-test.lxd` bzw. stage-only prüfen.
2. Prod-Rolle anwenden (Provisioner erhält DELETE).
3. LeagueSphere-Release; die App-Migration legt `may_insert`/`may_delete` an.
4. `tick.sh` kommt mit dem App-Checkout (`ls.app.pull`, sparse `deployed/`); kein
   manuelles `git pull` auf dem Server.

# JARVIS vom Server sicher nach GitHub hochladen

Dauer: etwa 15 Minuten. Dein laufender JARVIS wird dabei **nicht** verändert,
gestoppt oder neu gestartet. Das Skript liest den JARVIS-Ordner nur.
Abbrechen kannst du jederzeit mit **Strg + C**. Dann wird nichts hochgeladen.

## Was du vorher brauchst

- [ ] **Einen Computer** (Windows-PC oder Mac), kein Handy. Du musst Text kopieren und einfügen.
- [ ] **Die Zugangsdaten deines Servers:** IP-Adresse (z. B. `85.215.12.34`),
      Benutzername (meistens `root`) und Passwort. Du findest sie in der E-Mail, die du beim
      Mieten des Servers bekommen hast, oder im Kundenkonto deines Anbieters unter „Server“ oder „VPS“.
- [ ] **Deinen GitHub-Login.** Melde dich im Browser schon einmal auf github.com an.

## Schritt 1: Welche Art Server hast du?

- Meldest du dich mit **„Remotedesktopverbindung“** an und siehst dann einen Windows-Bildschirm
  mit Startmenü? Dann hast du einen **Windows-Server**. Mach weiter mit **Teil B**.
- In allen anderen Fällen hast du sehr wahrscheinlich einen **Linux-Server**. Das ist der
  häufigste Fall, zum Beispiel wenn dein Anbieter „Ubuntu“ oder „Debian“ schreibt oder du ein
  „root-Passwort“ bekommen hast. Mach weiter mit **Teil A**.

## Teil A: Linux-Server

1. **Programm auf deinem Computer öffnen**
   - Windows-PC: Drücke die Windows-Taste, tippe `PowerShell` und drücke Enter.
     Es öffnet sich ein blaues oder schwarzes Fenster.
   - Mac: Drücke Cmd + Leertaste, tippe `Terminal` und drücke Enter.
2. **Mit dem Server verbinden:** Tippe Folgendes und ersetze dabei `DEINE-IP` durch die
   echte Adresse:
   ```
   ssh root@DEINE-IP
   ```
   Beispiel: `ssh root@85.215.12.34`. Danach Enter drücken.
3. Beim ersten Mal fragt das Fenster
   `Are you sure you want to continue connecting (yes/no/[fingerprint])?`.
   Tippe `yes` und drücke Enter.
4. Bei `password:` tippst du dein Server-Passwort und drückst Enter.
   **Beim Tippen siehst du keine Zeichen und keine Sternchen. Das ist normal.**
5. Du bist verbunden, wenn so etwas erscheint: `root@dein-server:~#`
6. **Den Start-Befehl einfügen:** Markiere den grauen Kasten unten und kopiere ihn
   (Strg + C, am Mac Cmd + C). Klicke dann mit der **rechten Maustaste** in das Fenster
   (am Mac Cmd + V) und drücke Enter.
   ```bash
   curl -fsSLO https://raw.githubusercontent.com/Razhwan03/wirkstatt-website/refs/heads/claude/jarvis-mailbox-org-integration-68duut/tools/jarvis-export/jarvis_export.py && python3 jarvis_export.py
   ```
7. Weiter mit **Teil C**.

## Teil B: Windows-Server

1. Melde dich wie gewohnt per Remotedesktop am Server an.
2. Klicke **auf dem Server** auf Start, tippe `PowerShell` und drücke Enter.
3. Kopiere diesen Befehl, füge ihn mit einem Rechtsklick in das Fenster ein und drücke Enter:
   ```powershell
   curl.exe -fsSLO https://raw.githubusercontent.com/Razhwan03/wirkstatt-website/refs/heads/claude/jarvis-mailbox-org-integration-68duut/tools/jarvis-export/jarvis_export.py; python jarvis_export.py
   ```
4. Weiter mit **Teil C**.

## Teil C: Die Fragen des Skripts beantworten

1. **Ordner wählen.** Du siehst eine Liste, zum Beispiel:
   ```
   [1] /root/jarvis
       laufender Prozess (PID 1234): python3 main.py, 85 Python-Dateien
   ```
   Tippe die Nummer des Eintrags mit **„laufender Prozess“** oder **„systemd-Dienst“**
   (meistens `1`) und drücke Enter. Wenn du unsicher bist, schick mir ein Bildschirmfoto.
2. **Warten.** Danach laufen Backup und Prüfung von selbst. Das dauert 1 bis 5 Minuten.
   Du siehst dabei „Schritt 2/6“, „Schritt 3/6“ und so weiter.
3. **Einmalige Freigabe bei GitHub (Schritt 5/6).** Das Fenster zeigt einen Link und eine
   lange Zeile, die mit `ssh-ed25519` beginnt.
   1. Kopiere die lange Zeile: Markiere sie mit gedrückter linker Maustaste von `ssh-ed25519`
      bis zum Ende (`jarvis-server-deploy-key`). Unter Windows kopiert ein Rechtsklick oder
      Strg + C, am Mac Cmd + C.
   2. Öffne im Browser: <https://github.com/Razhwan03/-jarvis/settings/keys/new>
      GitHub fragt vielleicht noch einmal nach deinem Passwort oder einem Code. Das ist normal.
   3. Feld **Title:** `JARVIS Server`
   4. Feld **Key:** einfügen mit Strg + V (am Mac Cmd + V)
   5. Setze den Haken bei **Allow write access**.
   6. Klicke auf **Add key**.
   7. Drücke zurück im Fenster Enter. Dort steht dann „Zugang zu GitHub funktioniert.“

   Dieser Schlüssel gilt **nur** für das Repository `-jarvis`, für nichts anderes.
4. **Bestätigen.** Das Skript zeigt, welche Dateien hochgeladen werden. Wenn dort nur
   JARVIS-Dateien stehen, tippe `ja` und drücke Enter.
5. **Fertig.** Am Ende erscheint **FERTIG**. Schreib mir dann: **„Upload ist fertig“**.

## Wenn etwas nicht klappt

| Meldung | Was du tun musst |
|---|---|
| `Connection timed out` oder `Connection refused` | Die IP-Adresse ist falsch, oder SSH ist bei deinem Anbieter nicht freigeschaltet. Schreib mir den Namen deines Anbieters, dann sage ich dir, wo du klicken musst. |
| `Permission denied, please try again.` direkt nach der Passwort-Eingabe | Das Passwort ist falsch. Tippe es noch einmal und achte auf Groß- und Kleinschreibung. |
| `curl: command not found` | Stattdessen eingeben: `wget -q https://raw.githubusercontent.com/Razhwan03/wirkstatt-website/refs/heads/claude/jarvis-mailbox-org-integration-68duut/tools/jarvis-export/jarvis_export.py && python3 jarvis_export.py` |
| `python3: command not found` | Linux: `sudo apt-get install -y python3` eingeben, danach den Start-Befehl noch einmal. Windows: statt `python` versuche `py jarvis_export.py`. |
| `Das Programm 'git' fehlt` | Linux: `sudo apt-get install -y git openssh-client` eingeben, danach `python3 jarvis_export.py`. Windows: „Git for Windows“ installieren (https://git-scm.com/download/win). |
| `Permission denied` bei Dateien (nicht beim Login) | `sudo python3 jarvis_export.py` eingeben. |
| Keine Liste, oder der falsche Ordner | Strg + C drücken und mir ein Bildschirmfoto schicken. |
| `Nach der Bereinigung wurden noch Geheimnisse gefunden` | Es wurde nichts hochgeladen. Schick mir die Liste. Sie enthält nur Dateinamen, keine Passwörter. |
| Etwas anderes | Schick mir ein Bildschirmfoto oder die letzten Zeilen. Das Skript zeigt nie Passwörter an. |

**Bitte nie in den Chat schicken:** dein Server-Passwort, dein GitHub-Passwort oder den
Inhalt deiner `.env`-Datei.

## Was das Skript genau macht

1. Es findet den Ordner, mit dem dein laufender JARVIS arbeitet. Deinen ganzen
   Benutzerordner lehnt es ab.
2. Es legt ein **vollständiges Backup** an: `~/jarvis-backups/jarvis-backup-DATUM.tar.gz`.
   Darin ist alles, auch Passwörter, Datenbanken und noch nicht gespeicherte Änderungen.
   Das Backup **bleibt nur auf dem Server**.
3. Es baut eine **bereinigte Kopie** ohne `.env`, Passwörter, Schlüssel, Datenbank-Inhalte,
   Chats, Logs, private Daten und große Dateien.
4. Gefundene API-Schlüssel und Passwörter ersetzt es in der Kopie durch `REDACTED_BY_IMPORT`
   und prüft danach ein zweites Mal. Deine Originaldateien bleiben, wie sie sind.
5. Bevor es hochlädt, zeigt es dir die Dateien und fragt dich.
6. Es lädt die Kopie in dein **privates** Repository `Razhwan03/-jarvis` hoch.
   Es überschreibt nichts und benutzt keinen Force-Push.

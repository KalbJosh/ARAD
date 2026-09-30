# Einrichtung

Diese Anleitung beschreibt den Aufbau, der bei uns läuft: ein Linux-Rechner mit Autodarts und der ARAD-Bridge, dazu ein Beamer, der die Seite im Browser anzeigt. Überall, wo `<rechner>` steht, gehört die IP oder der Hostname deines Autodarts-Rechners hin.

## 1. Autodarts (Erkennung)

1. Autodarts **headless** installieren, siehe die [Autodarts-Doku](https://docs.autodarts.com/getting-started/detection/headless-installation/). Autodarts läuft danach als Benutzerdienst `autodarts` auf Port 3180.
2. **Der Dienst soll ohne Anmeldung starten**, also direkt nach dem Booten:
   ```bash
   loginctl enable-linger $USER
   ```
3. **Zugriff auf die Kameras erlauben.** Ohne diesen Schritt meldet Autodarts „0 device(s) found“:
   ```bash
   sudo usermod -aG video $USER && sudo reboot
   ```
4. Die **Terminal-App** starten. Die frühere Weboberfläche auf Port 3180 ist ab Version 2.0 abgeschaltet.
   ```bash
   ~/.local/bin/autodarts
   ```
   - Mit **Sign in** anmelden und ein Board anlegen oder übernehmen.
   - Die Kameras unter *Camera 1–3* zuweisen. Die automatische Zuordnung klappt nur mit genau 3 gleichnamigen Kameras.
5. **Kameras ausrichten und scharfstellen.** Jede Kamera muss den **kompletten Doppelring** sehen, mit etwas Rand. Unter `http://<rechner>:8090/focus` gibt es ein Live-Bild mit Schärfewert. Diese Seite ist erst verfügbar, wenn Schritt 2 erledigt ist.
6. Die Darts ziehen und in der Terminal-App **Calibrate** wählen. Pro Kamera wird ein Fehler in Pixeln angezeigt. Unter etwa 5 px ist gut. Kameras mit großem Fehler überspringt die Beamer-Einrichtung.

## 2. ARAD-Software

Vom eigenen Rechner aus, im Ordner dieses Repos:

```bash
bash setup/deploy.sh benutzer@<rechner>
```

Das Skript braucht **kein sudo**. Es richtet ein:
- Node LTS unter `~/.local/opt/node`
- Piper samt britischer Stimme für den Caller
- ein selbst signiertes Zertifikat für die HTTPS-Kalibrierseite
- den Benutzerdienst `arad-bridge`

Beim nächsten Aufruf aktualisiert es nur den Code. Die Kalibrierung auf dem Rechner bleibt erhalten.

Die Einstellungen stehen in `bridge/config.json`, danach `systemctl --user restart arad-bridge`:
- `fx`: `visitEnd` (Standard, Show nach der Aufnahme), `perDart` oder `off`
- `players`, `start`, `doubleOut`: Vorgaben für ein neues Spiel
- `caller.voice`: eine andere [Piper-Stimme](https://huggingface.co/rhasspy/piper-voices)
- `ledUrl`: optional ein LED-Ringlicht über den Pi Zero

Die Protokolle stehen hier:
```bash
journalctl --user -u arad-bridge -f
```

## 3. Beamer

- Den Beamer mittig vor die Wand stellen. **Links steht das Scoreboard, rechts die Scheibe.** Das Bild sollte die ganze Scheibe samt Surround abdecken.
- Am Beamer einen Browser öffnen und `http://<rechner>:8090/` im **Vollbild** aufrufen. Wir nutzen einen Xiaomi L1 mit einem Browser aus dem Play Store.
- Einmal **OK** auf der Fernbedienung drücken, dann gibt der Browser den Ton frei.
- Am L1 **Auto-Trapezkorrektur und Autofokus beim Einschalten deaktivieren.** Sonst verschiebt sich das Bild bei jedem Start.

## 4. Beamer einrichten (per Knopfdruck)

Handy → `http://<rechner>:8090/remote` → **🎯 Beamer automatisch einrichten**. Die Scheibe muss dabei leer sein, der Raum eher dunkel.

Was passiert, in etwa einer Minute:
1. Autodarts wird neu gestartet, dann wartet die Seite, bis die Kameras Bilder liefern.
2. Der Beamer blendet Punktraster ein. Jeder Punkt blinkt in seinem eigenen Binärcode.
3. Jede Kamera rechnet die Punkte, die sie auf der Scheibe sieht, über ihre Autodarts-Kalibrierung in Millimeter um. Daraus entsteht die Zuordnung Scheibe ↔ Beamer. Punkte auf der Wand werden verworfen, weil die Wand in einer anderen Ebene liegt.
4. Zur Kontrolle erscheint 4 s lang ein Gitter. Danach startet Autodarts neu, damit es sich das neue Licht als Normalzustand merkt.

Die Einrichtung läuft **auf dem Beamer selbst**, das Handy gibt nur den Auftrag und darf dabei ausgehen. Nötig ist sie nur, wenn der Beamer oder die Scheibe bewegt wurde.

Ohne Autodarts-Kameras geht es auch mit dem Handy: `https://<rechner>:8443/calib`. Beim ersten Aufruf musst du die Zertifikatswarnung bestätigen.

## Stolpersteine (die wir gefunden haben)

- **Licht auf der Scheibe stört Autodarts.** Jeder Lichtwechsel wirkt auf Autodarts wie eine Hand, und es bleibt im „Takeout“ hängen. Deshalb kommt die Show erst nach der Aufnahme, und im Spiel bewegt sich an der Wand nichts. Hängt Autodarts trotzdem, startet die Bridge es selbst neu. Ein reines „Reset“ genügt nicht, weil dabei das Referenzbild bleibt.
- **Das Autodarts-Kamerabild (`/api/img/cams/N`) kommt verzögert**, 0,4 bis über 3 s, im Dunkeln stärker. Die Einrichtung wartet deshalb bei jedem Muster auf ein aktuelles Bild.
- **Android-TV-Browser zoomen heraus,** wenn ein Element breiter ist als der Bildschirm. Dann wird rechts abgeschnitten. Die Beamerseite hält deshalb alles in einem festen Rahmen. Sie meldet Bildgröße und Fehler an die Bridge (`[Beamer]` im Protokoll) und lässt sich von dort neu laden.

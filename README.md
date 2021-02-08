# Der D64 Covidbot
Ein Bot zu Deinen Diensten: Unser Covidbot versorgt Dich einmal am Tag mit den aktuellen Infektions-, Todes- und Impfzahlen der von Dir ausgewählten Orte.
Abonniere ihn einfach in Deinem Lieblingsmessenger, indem Du den Telegram-Bot startest oder bei Signal oder Threema eine Nachricht mit "Start" schickst, nachdem Du den Bot als Kontakt hinzugefügt hast.
[Telegram](https://t.me/CovidInzidenzBot) | [Threema](https://threema.id/*COVINFO?text=Start) | Signal (Beta): Füge +4915792453845 als Kontakt hinzu

## Features
Du kannst einfach eine Nachricht mit dem Stadt-/Landkreis, Bundesland oder einem Standort an den Bot senden.
Dann erhälst du eine Liste mit möglichen Orten oder Aktionen, bspw. "Bericht" für die aktuellen Daten oder "Starte Abo" um diesen zu abonnieren.

Außerdem gibt es diese Befehle:
* `/hilfe` bzw. `/start`: Überblick über die Befehle
* `/ort $1`: Aktuelle Daten für `$1`
* `/abo $1`: Abonniere tägliche Daten für `$1`
* `/beende $1`: Beende Abonnement für `$1`
* `/bericht`: Zeige den aktuellen Bericht mit der Coronainzidenz
* `/statistik`: Nutzungsstatistik
* `/datenschutz`: Datenschutzerklärung
* `/loeschmich`: Lösche alle Daten


## Installation (für Telegram)
Die aktuelle Version kann man unter [@CovidInzidenzBot](https://t.me/CovidInzidenzBot) benutzen.

Für einen eigenen Telegrambot muss die Konfiguration von `resources/config.default.ini` nach `config.ini` kopiert und ausgefüllt werden.
Danach kann er über `python3 -m covidbot` gestartet werden.

## Credits
Die Informationen über die Corona-Infektionen werden von der offiziellen Schnittstelle des RKI für [Landkreise](https://hub.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0) und [Bundesländer](https://npgeo-corona-npgeo-de.hub.arcgis.com/datasets/ef4b445a53c1406892257fe63129a8ea_0) abgerufen und stehen unter der Open Data Datenlizenz Deutschland – Namensnennung – Version 2.0.
Weitere Informationen sind auch im [Dashboard des RKI](https://corona.rki.de/) sowie dem [NPGEO Corona Hub 2020](https://npgeo-corona-npgeo-de.hub.arcgis.com/) zu finden.

Welche Bibliotheken und andere Dienste wir noch verwenden, kannst Du unter [Credits](https://github.com/eknoes/covid-bot/wiki/Credits) im Wiki einsehen.

## Ein Projekt von D64 - Zentrum für Digitalen Fortschritt
D64 versteht sich als Denkfabrik des digitalen Wandels. Wir sind von der gesamtgesellschaftlichen Auswirkung des Internets auf sämtliche Bereiche des öffentlichen und privaten Lebens überzeugt. D64 will Taktgeber und Ratgeber für die Politik sein, um Deutschland für die digitale Demokratie aufzustellen. Leitgedanke des Vereins ist die Frage, wie das Internet dazu beitragen kann, eine gerechte Gesellschaft zu fördern. Wir finanzieren uns ausschließlich durch Mitgliedsbeiträge. [Werde Mitglied und hilf mit, das Internet freier, gerechter und solidarischer zu machen!](https://d-64.org/mitglied-werden/)

[Datenschutzerklärung](https://github.com/eknoes/covid-bot/wiki/Datenschutz) | [Impressum](https://github.com/eknoes/covid-bot/wiki/Impressum)

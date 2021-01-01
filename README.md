# Telegram COVID-19 Bot
Dies ist ein Telegrambot, der aktuelle COVID-19 Zahlen für verschiedene Orte bereitstellt.
Es können mehrere Orte und Bundesländer abonniert werden können, sodass bei neuen Zahlen des Robert-Koch-Instituts (RKI) eine Zusammenfassung mit den relevanten Orten bereitgestellt wird.
Der aktuelle Prototyp läuft unter [@CovidInzidenzBot](https://t.me/CovidInzidenzBot) und ist Work in Progress.

## Features
* `/hilfe` bzw. `/start`: Überblick über die Befehle
* `/ort $1`: Aktuelle Daten für `$1`
* `/abo $1`: Abonniere tägliche Daten für `$1`
* `/beende $1`: Beende Abonnement für `$1`
* `/bericht`: Zeige den aktuellen Bericht mit der Coronainzidenz

## Installation
Die aktuelle Version kann man unter [@CovidInzidenzBot](https://t.me/CovidInzidenzBot) benutzen.

Für einen eigenen Telegrambot muss der Telegram API Key unter `.api_key` hinterlegt werden.
Danach kann er über `python3 -m covidbot` gestartet werden.

## Credits
Die Informationen über die Corona-Infektionen werden von der offiziellen Schnittstelle des RKI für [https://hub.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0](Landkreise) und [https://npgeo-corona-npgeo-de.hub.arcgis.com/datasets/ef4b445a53c1406892257fe63129a8ea_0](Bundesländer) abgerufen und stehen unter der Open Data Datenlizenz Deutschland – Namensnennung – Version 2.0.
Weitere Informationen sind auch im [https://corona.rki.de/](Dashbord des RKI) sowie dem [https://npgeo-corona-npgeo-de.hub.arcgis.com/](NPGEO Corona Hub 2020) zu finden.

Die Zuordnung von Standorten, Postleitzahlen und Dörfern/Städten, die selbst keine Stadt- oder Landkreise sind, zu Stadt- oder Landkreisen (die Ebene auf der die Informationen vom RKI zur Verfügung gestellt werden), erfolgt mit Hilfe von [https://nominatim.openstreetmap.org/](Nominatim), welches durch OpenStreetMap zur Verfügung gestellt wird, © OpenStreetMap contributors, ODbL 1.0. https://osm.org/copyright.

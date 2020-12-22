# Telegram COVID-19 Bot
Dies ist ein Telegrambot, der aktuelle COVID-19 Zahlen für verschiedene Orte bereitstellt.
Es können mehrere Orte und Bundesländer abonniert werden können, sodass bei neuen RKI Zahlen eine Zusammenfassung mit den relevanten Orten bereitgestellt wird.
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

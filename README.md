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
Die Informationen über die Corona-Infektionen werden von der offiziellen Schnittstelle des RKI für [Landkreise](https://hub.arcgis.com/datasets/917fc37a709542548cc3be077a786c17_0) und [Bundesländer](https://npgeo-corona-npgeo-de.hub.arcgis.com/datasets/ef4b445a53c1406892257fe63129a8ea_0) abgerufen und stehen unter der Open Data Datenlizenz Deutschland – Namensnennung – Version 2.0.
Weitere Informationen sind auch im [Dashboard des RKI](https://corona.rki.de/) sowie dem [NPGEO Corona Hub 2020](https://npgeo-corona-npgeo-de.hub.arcgis.com/) zu finden.

Die Zuordnung von Standorten, Postleitzahlen und Dörfern/Städten, die selbst keine Stadt- oder Landkreise sind, zu Stadt- oder Landkreisen (die Ebene, auf der die Informationen vom RKI zur Verfügung gestellt werden), erfolgt mit Hilfe von [Nominatim](https://nominatim.openstreetmap.org/), welches durch OpenStreetMap zur Verfügung gestellt wird, © OpenStreetMap contributors, ODbL 1.0. https://osm.org/copyright.

### Open Source-Bibliotheken
Im Übrigen wäre dieses Projekt nicht möglich ohne die vielen großartigen, frei verfügbaren Bibliotheken, die uns zur Verfügung stehen. Vielen Dank an alle Beteiligten!

Wir verwenden die folgenden Bibliotheken:

* [Advanced Python Scheduler (APScheduler)](https://github.com/agronholm/apscheduler), MIT License (MIT), Copyright (c) 2021 Alex Grönholm
* [certifi](https://github.com/certifi/python-certifi), Mozilla Public License 2.0 (MPL 2.0), Copyright (c) 2021 Kenneth Reitz
* [cffi](https://cffi.readthedocs.io/en/latest/), MIT License (MIT), Copyright (c) 2021 Armin Rigo, Maciej Fijalkowski
* [chardet](https://github.com/byroot/chardet), GNU Library or Lesser General Public License (LGPL), Copyright (c) 2021 Mark Pilgrim
* [cryptography](https://github.com/pyca/cryptography), Apache Software License, BSD License (BSD or Apache License, Version 2.0), Copyright (c) 2021 The cryptography developers
* [decorator](https://github.com/micheles/decorator), BSD License (new BSD License), Copyright (c) 2021 Michele Simionato
* [flake8](https://gitlab.com/pycqa/flake8), MIT License (MIT), Copyright (c) 2021 Tarek Ziade
* [idna](https://github.com/kjd/idna), BSD License (BSD-3-Clause), Copyright (c) 2021 Kim Davies
* [mccabe](https://github.com/pycqa/mccabe), MIT License (Expat license), Copyright (c) 2021 Ian Cordasco
* [psycopg2](https://psycopg.org/), GNU Library or Lesser General Public License (LGPL) (LGPL with exceptions), Copyright (c) 2021 Federico Di Gregorio
* [pycodestyle](https://pycodestyle.readthedocs.io/), MIT License (Expat license), Copyright (c) 2021 Johann C. Rocholl
* [pycparser](https://github.com/eliben/pycparser), BSD License (BSD), Copyright (c) 2021 Eli Bendersky
* [pyflakes](https://github.com/PyCQA/pyflakes), MIT License (MIT), Copyright (c) 2021 A lot of people
* [python-telegram-bot](https://python-telegram-bot.org/), GNU Lesser General Public License v3 (LGPLv3), Copyright (c) 2021 Leandro Toledo
* [pytz](http://pythonhosted.org/pytz), MIT License (MIT), Copyright (c) 2021 Stuart Bishop
* [requests](https://requests.readthedocs.io/), Apache Software License (Apache 2.0), Copyright (c) 2021 Kenneth Reitz
* [six](https://github.com/benjaminp/six), MIT License (MIT), Copyright (c) 2021 Benjamin Peterson
* [tornado](http://www.tornadoweb.org/), Apache Software License, Copyright (c) 2021 Facebook
* [tzlocal](https://github.com/regebro/tzlocal), MIT License (MIT), Copyright (c) 2021 Lennart Regebro
* [urllib3](https://urllib3.readthedocs.io/), MIT License (MIT), Copyright (c) 2021 Andrey Petrov

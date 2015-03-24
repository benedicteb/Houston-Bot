Houston-Bot
===========

Dette er en chattebot utviklet for Houston førstelinje, USIT, Universitetet i
Oslo. Den poster statistikk fra saksbehandlingssystemet, registrerer besøksdata
og og melder fra om driftsmeldinger.

Den bruker en `sqlite`-database for lagring av brukere og besøksdata. Du har
muligheten til å bestille kopi av besøksdata på csv sendt til din epost.

Den kan startes ved å kalle på main-filen

```
python RTBot.py
```

og vil da spørre om nødvendig credentials. Den trenger en konto som har tilgang
til køer i RT, en UiO-konto for sending av epost og en chattekonto som har
tilgang til UiOChat.

I grunnen skal den være generell men har vokst til å bli veldig
Houston-spesifikk.

Bidra hvis du vil! Send pull requests til `dev`-tråden så legger vi inn i
`master` når vi vet ting virker.

UiO-RT-Bot
==========

This is an XMPP bot for retrieving info from the RT (Request Tracker) system
used to manage tickets at UiO.

## Features

Can broadcast status of chosen queues at interval:

```
(bot) 'queue' : 99 unowned of total 99999 tickets.
```

Retrieves info when ticket ids are mentioned:

```
(person) this is a ticket #999
(bot) subject of ticket - owner - status - requestors - link to ticket
```

The bot searches for the `#` so be sure to put that in front of your int to
signal that it is a ticket.

## Usage

Just call the main py-script. It asks for chat credentials and RT credentials.
Remember to never activate the bot in an open channel if your RT user has access
to sensitive information since then anyone can get information. However it is
not possible to communicate privately with the bot. So if the bot is active in a
restricted channel, you should be safe.

Call with `--broadcast` for broadcasting. At this time you cannot customize the
interval, it is set to hourly. However that will come later.

First time booting the bot will ask for chat-room and queue, however these will
be saved to files `default_chatrooms.txt` and `queues.txt`, where you then can
add lines with queues and rooms if you want the bot to be in more rooms or fetch
status from several queues.

## Contribute

Feel free to fork and send pull requests! This is something I cooked up in my
spare time in a couple of hours, and it's definetely not perfect.

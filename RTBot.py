#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import re
import os
import logging
import datetime
import random
import threading
import argparse

import urllib
import urllib2
import time
import xmpp
import sqlite3
import csv
import smtplib
import feedparser
import mimetypes
import shlex

from jabberbot import JabberBot, botcmd
from getpass import getpass
from sqlalchemy import func
from sqlalchemy.sql import exists

from pyRT.src.RT import RTCommunicator
from Emailer import Emailer

_PREFFILE = 'dbpath.txt'
_FEEDSFILE = 'rtbot.feeds.txt'

"""CONSTANTS"""
_FORGOTTEN_KOH =\
u"""
Hei,

det ble glemt å registrere antall besøkende med meg i dag..


hilsen Anna
"""
_EXPORT_KOH = \
u"""
Hei,

her er filen med eksporterte KOH-data.


hilsen Anna
"""
_DRIFT_URL = "http://www.uio.no/tjenester/it/aktuelt/driftsmeldinger/?vrtx=feed"
_PACKAGE_TEXT = \
u"""
Hei,

det har kommet en ny pakke til dere (%s) fra %s uten e-nummer. Den kan hentes i
Houston-resepsjonen.

Oppgi koden %d når du kommer for å hente den.

Eventuelle notater: %s


hilsen Anna
"""
_PACKAGE_TEXT_EN = \
u"""
Hei,

det har kommet en ny pakke til dere (%s) fra %s med e-nummer %s. Den kan hentes
i Houston-resepsjonen.

Oppgi koden %d når du kommer for å hente den.

Eventuelle notater: %s


hilsen Anna
"""
_PACKAGE_KVIT = \
u"""
Hei,

dette er en bekreftelse på at du (%s) hentet pakken med id %d her i
Houston-resepsjonen.


hilsen Anna
"""

"""CLASSES"""
class MUCJabberBot(JabberBot):
    """
    Middle-person class for adding some MUC compatability to the Jabberbot.
    """
    def __init__(self, *args, **kwargs):
        # answer only direct messages or not?
        self.only_direct = kwargs.get('only_direct', False)

        try:
            del kwargs['only_direct']
        except KeyError:
            pass

        # initialize jabberbot
        super(MUCJabberBot, self).__init__(*args, **kwargs)

        # create a regex to check if a message is a direct message
        self.direct_message_re = r'#(\d+)'

        # Message queue needed for broadcasting
        self.thread_killed = False

    def callback_message(self, conn, mess):
        message = mess.getBody()
        if not message:
            return

        message_type = mess.getType()
        tickets = re.findall(self.direct_message_re, message)

        if message_type == 'chat' and re.search('rtinfo', mess.getBody()):
            mess.setBody('private')
        if re.search('#morgenru', message):
            mess.setBody('morgenrutiner')
        if re.search('#kveldsru', message):
            mess.setBody('kveldsrutiner')
        if len(tickets) != 0:
            mess.setBody('rtinfo %s' % tickets[0])

        return super(MUCJabberBot, self).callback_message(conn, mess)

class RTBot(MUCJabberBot):
    def __init__(self, username, password, queues, admin):
        """
        queues is which queues to broadcast status from.
        """
        self.joined_rooms = []
        self.queues, self.db, self.admin = queues, db, admin
        super(RTBot, self).__init__(username, password, only_direct=True)

    @botcmd
    def pakke(self, mess, args):
        """
        Brukes for å ta imot pakker, liste dem opp og markere de som hentet.
        """
        words = shlex.split(mess.getBody().strip().encode('UTF-8'))
        chatter, resource = str(mess.getFrom()).split('/')

        if not self.is_authenticated(chatter):
            logging.warning('%s tried to run pakke and was shown out.' % chatter)
            return "You are neither an op, admin or user. Go away!"

        parser = argparse.ArgumentParser(description='pakke command parser')
        parser.add_argument('command', choices=['ny', 'uhentede', 'hent',
            'siste', 'show'])
        parser.add_argument('--recipient', default=False)
        parser.add_argument('--sender', default=False)
        parser.add_argument('--enummer', default='')
        parser.add_argument('--id', default=None, type=int)
        parser.add_argument('--picker', default=False)
        parser.add_argument('--email', default=False)
        parser.add_argument('--notes', default='')

        try:
            args = parser.parse_args(words[1:])
        except:
            logging.info('%s used bad syntax for pakke.' % chatter)
            return 'Usage: pakke ny/uhentede/hent/siste --recipinet recipient --sender sender --enummer enummer --notes notes'

        if args.command == 'ny':
            if not args.recipient or not args.sender or not args.email:
                logging.info('%s did not give enough info for ny pakke.' % chatter)
                return 'Recipient, sender and contact e-mail is mandatory.'

            now = datetime.datetime.now()
            dt_str = datetime.datetime.strftime(now, '%Y-%m-%d %H:%M:%S')

            s = db.load_session()
            max_id = s.query(func.max(db.Package))
            s.close()

            if max_id == None:
                new_id = 0
            else:
                new_id = max_id + 1

            new_package = db.Package(recipient=args.recipient,
                    sender=args.sender, enummer=args.enummer, email=args.email,
                    notes=args.notes, registrert_av=chatter)

            s = db.load_session()
            s.add(new_package)
            s.commit()
            s.close()

            logging.info('%s added package-line\n  "%s"'\
                    % (chatter, str(indata)))

            if args.enummer:
                self.emailer.send_email(args.email, u'Ny pakke fra %s, hente-id: %d'\
                        % (args.sender, new_id), _PACKAGE_TEXT_EN % (args.recipient,
                            args.sender, args.enummer, new_id, args.notes) )
            else:
                self.emailer.send_email(args.email, u'Ny pakke fra %s, hente-id: %d'\
                        % (args.sender, new_id), _PACKAGE_TEXT % (args.recipient,
                            args.sender, new_id, args.notes) )

            return 'OK, package registered with id %d and e-mail sent to %s.' % (new_id, args.email)
        elif args.command == 'uhentede':
            s = db.load_session()
            rs = s.query(db.Package).filter_by(hentet=False).all()

            ostring = '\n%5s %20s %20s %20s %10s' % ('Id', 'Date recieved', 'Sender', 'Recipient', 'E-nummer')

            for pack in rs:
                ostring += '\n%5d %20s %20s %20s %10s' % (pack.id,
                        pack.date_added, pack.sender, pack.recipient,
                        pack.enummer)

            s.close()
            logging.info('%s listed all un-fetched packages.' % chatter)
            return ostring
        elif args.command == 'hent':
            if args.id == None or not args.picker:
                logging.warning('%s tried to pickup package without id or picker.'\
                                % chatter)
                return 'Specify id and picker-upper with\n  pakke hent --id id --picker "person som plukker opp"'

            s = db.load_session()

            try:
                pack = s.query(db.Package).filter_by(id=args.id).one()
            except Exception, e:
                logging.warning(e)
                logging.warning('%s tried to pickup non-existing package.'\
                        % chatter)
                return 'No such package.'

            pack.hentet = True
            pack.hentet_av = args.picker
            pack.hentet_da = datetime.datetime.utcnow()
            pack.registrert_hentet_av = chatter

            s.commit()
            s.close()

            self.emailer.send_email(pack.email, 'Kvittering på hentet pakke %d'\
                    % args.id, _PACKAGE_KVIT % (args.picker, args.id) )

            return 'OK, pakke med id %d registrert som hentet av %s.' % (args.id, args.picker)
        elif args.command == 'siste':
            s = db.load_session()
            rs = s.query(db.Package).order_by(db.Package.id.desc()).all()

            ostring = '\n%5s %20s %20s %20s %10s' % ('Id', 'Date recieved', 'Sender', 'Recipient', 'E-nummer')

            counter = 1
            for pack in rs:
                ostring += '\n%5d %20s %20s %20s %10s' % (pack.id,
                        pack.date_added, pack.sender, pack.recipient,
                        pack.enummer)
                counter += 1
                if counter == 10:
                    break

            s.close()

            logging.info('%s listed last 10 packages.' % chatter)
            return ostring
        elif args.command == 'show':
            if args.id == None:
                return 'You can only show with id.'
            return "Not implemented yet."

    @botcmd
    def useradmin(self, mess, args):
        """
        Can be used to set user permissions and add users.
        """
        words = shlex.split(mess.getBody().strip().encode('UTF-8'))
        chatter, resource = str(mess.getFrom()).split('/')

        if not self.is_op(chatter) and chatter != self.admin:
            dbconn.close()
            logging.info('%s tried to call useradmin.' % chatter)
            return 'You are not an op nor an admin.'

        parser = argparse.ArgumentParser(description='useradd command parser')
        parser.add_argument('level', choices=['op', 'user', 'list'],
                help='What kind of permission level to give.')
        parser.add_argument('--jid', help='Username of person to add.',
                default=chatter)

        try:
            args = parser.parse_args(words[1:])
        except:
            logging.info('%s used bad syntax for useradmin.' % chatter)
            return 'Usage: useradd op/user/list --jid username@domain'

        s = db.load_session()
        users = s.query(db.User).all()

        if args.level == 'op':
            if self.is_op(args.jid):
                return '%s is already an op.' % args.jid

            new_op = db.Op(jid=args.jid)
            s.add(new_op)
            s.commit()
            s.close()

            logging.info('%s made %s an op.' % (chatter, args.jid))
            return 'OK, made %s an op.' % args.jid
        elif args.level == 'user':
            if self.is_user(args.jid):
                return '%s is already a user.' % args.jid

            new_user = db.User(jid=args.jid)
            s.add(new_user)
            s.commit()
            s.close()

            logging.info('%s made %s a user.' % (chatter, args.jid))
            return 'OK, made %s a user.' % args.jid
        elif args.level == 'list':
            ostring = '--- OPS: ---'

            for op in self.get_ops():
                ostring += '\n* %s' % op.jid

            ostring += '\n--- USERS: ---'

            for user in self.get_users():
                ostring += '\n* %s' % user.jid

            s.close()

            logging.info('%s listed all users and ops.' % chatter)
            return ostring

    @botcmd
    def listkoh(self, mess, args):
        """
        Lists last 10 entries in kos table.
        """
        chatter, resource = str(mess.getFrom()).split('/')

        if not self.is_user(chatter) and not self.is_op(chatter):
            logging.info('%s, not op nor user tried to run kohbesok.' % chatter)
            return 'You are neither a registered user or op, go away!'

        output = ""
        counter = 0

        try:
            s = db.load_session()
            rows = s.query(db.Besok).order_by(db.Besok.date.desc()).all()
        except Exception, e:
            print e

        for row in rows:
            output += '%10s: %4d\n' % (row.date.strftime('%Y-%m-%d'), row.visitors)
            counter += 1

            if counter == 10:
                break

        s.close()

        logging.info('%s listed last 10 koh visits.' % chatter)
        return output

    @botcmd
    def kohbesok(self, mess, args):
        """
        This command is used for editing entries in the KOH-visitors database.
        You can 'register' and 'edit'. Usually the commands follow the syntax:

        kohbesok register number

        This assumes you want to register for todays date. If you specify with
        date:

        kohbesok register number --date 2015-01-01

        The number will be registered for the date you specify.

        Editing is done like so:

        kohbesok edit newnumber --date YYYY-mm-dd

        Here the date will also be assumed to be today if you don't specify it.
        """
        words = shlex.split(mess.getBody().strip().encode('UTF-8'))
        now = datetime.datetime.now()
        d = now.strftime('%Y-%m-%d')
        chatter, resource = str(mess.getFrom()).split('/')

        parser = argparse.ArgumentParser(description='kohbesok command parser')
        parser.add_argument('command', choices=['register', 'edit'],
                help='What to do.')
        parser.add_argument('visitors', type=int, help='Number of visitors.')
        parser.add_argument('--date', help='Can override todays date.',
                default=d)

        try:
            args = parser.parse_args(words[1:])
            date_parsed = datetime.datetime.strptime(args.date, '%Y-%m-%d')
        except:
            logging.info('%s used bad syntax for kohbesok.' % chatter)
            return 'Usage: kohbesok register/edit visitors [--date YYYY-mm-dd]'

        if not self.is_user(chatter) and not self.is_op(chatter):
            logging.info('%s, not op nor user tried to run kohbesok.' % chatter)
            return 'You are neither a registered user or op, go away!'

        if args.command == 'register':
            # Check if in future
            if date_parsed > now:
                logging.info('%s tried to register %d for %s ignored since in future.' % (chatter, args.visitors, args.date))
                return 'You cannot register for dates in the future.'

            s = db.load_session()
            if s.query(exists().where(db.Besok.date==date_parsed)).scalar():
                return "This date is already registered."

            s.add(db.Besok(visitors=args.visitors, date=date_parsed))
            s.commit()
            s.close()

            logging.info('%s registered %d koh-visitors for %s' \
                    % (chatter, args.visitors, args.date))
            return 'OK, registered %d for %s.' % (args.visitors, args.date)
        elif args.command == 'edit':
            if not self.is_op(chatter):
                logging.info('%s (not op) tried to edit koh post.' % chatter)
                return "You are not an op and cannot edit."

            s = db.load_session()
            try:
                besok = s.query(db.Besok).filter_by(date=date_parsed).one()
            except Exception, e:
                logging.info('%s tried to edit non-existing data' % chatter)
                return "There is no data on this date yet."

            old_value = besok.visitors
            besok.visitors = args.visitors

            s.commit()
            s.close()

            logging.info('%s changed %d to %d for %s' % (chatter, old_value,
                args.visitors, args.date))

            return "OK, updated data for %s. Changed %d to %d."\
                    % (args.date, old_value, args.visitors)

    @botcmd
    def rtinfo(self, mess, args):
        """
        Tells you some RT info for given ticket id.
        """
        ticket_id = str(mess.getBody().split()[-1])
        return self.RT.rt_string(ticket_id)

    @botcmd
    def morgenrutiner(self, mess, args):
        """
        Tells the morgenrutiner.
        """
        infile = open('morgenrutiner.txt', 'r')
        text = infile.read()
        infile.close()
        return text

    @botcmd
    def kveldsrutiner(self, mess, args):
        """
        Tells the kveldsrutiner.
        """
        infile = open('kveldsrutiner.txt', 'r')
        text = infile.read()
        infile.close()
        return text

    def godmorgen(self):
        """
        Si god morgen.
        """
        hilsen = "God morgen, førstelinja! "

        ekstra = [
            "Hva skjer?",
            "Ønsker dere en fin dag!",
            "Jeg føler at dette blir en effektiv dag.",
            "Er det fint vær i dag?",
            "Ikke glem å spise frokost.",
            "Æsj, hvor ble det av kaffen min?",
            "... Where there's a whip, there's a way!",
            "Hold the waterworks till the end of the day there hun'",
            "Kommer det mange pakker i dag?",
            "Har lokal-IT kommet på jobb tro?",
            "Føler meg ikke bra jeg, sov så dårlig i natt..",
            "We're workin' nine to five!",
            "Dere er awesome!",
            "Hvor mange brukere tror vi det kommer innom i dag?",
            "Husk å vise HF at dere liker dem litt, viktig med kjærlighet.",
            "Har dere husket å logge på telefonene?",
            "Kom med flere idéer til hva jeg kan si om morgenen. Ække så lett å finne på ting..",
            "Jeg er glad i dere!",
            "Kos dere på jobb!",
            "Lykke til med jobb!",
            "Dere er kule!",
            "This was a triumph, I'm making a note here, HUGE SUCCESS!",
            "The cake is a lie.",
        ]

        return hilsen + random.choice(ekstra)

    def godkveld(self):
        """
        Si god kveld.
        """
        return "God kveld alle sammen!"

    @botcmd
    def exportkoh(self, mess, args):
        """
        Exports koh data.
        """
        parser = argparse.ArgumentParser(description='command parser')
        parser.add_argument('start', help='From-date.')
        parser.add_argument('end', help='To-date.')
        parser.add_argument('email', help='E-mail to send file to.')

        try:
            args = parser.parse_args(mess.getBody().strip().split()[1:])
        except:
            return 'Usage: exportkoh start-date(YYYY-mm-dd) end-date email'

        filename = 'koh.csv'

        if os.path.isfile(filename):
            os.remove(filename)

        csvfile = open(filename, 'wb')
        writer = csv.writer(csvfile, delimiter=' ',
                quotechar='|', quoting=csv.QUOTE_MINIMAL)

        logging.info('Finding all kohbesok between %s and %s' % (args.start, args.end))

        writer.writerow(['Date', 'Visitors'])

        s = db.load_session()

        rows = s.query(db.Besok).filter(db.Besok.date.between(args.start,
            args.end)).order_by(db.Besok.date)

        for row in rows:
            writer.writerow([row.date, row.visitors])

        s.close()

        csvfile.close()

        # Email it to asker
        self.emailer.send_email(args.email, 'Eksporterte KOH-data',
            _EXPORT_KOH, infile=filename)

        return "File written and sent to '%s'!" % args.email

    @botcmd
    def private(self, mess, args):
        """
        Tells user that this bot cannot communicate via private chat.
        """
        return "Sorry, I'm not allowed to talk privately."

    def join_room(self, room, *args, **kwargs):
        """
        Need a list of all joined rooms.
        """
        self.joined_rooms.append(room)
        super(RTBot, self).join_room(room, *args, **kwargs)

    def _post(self, text):
        """
        Takes a string and prints it to all rooms this bot is in.
        """
        for room in self.joined_rooms:
            message = "<message to='%s' type='groupchat'><body>%s</body></message>" % (room, text)
            self.conn.send(message)

    def _opening_hours(self, now):
        """
        Returns start / end ints representing end and opening hour.
        """
        if now.isoweekday() == 5:
            # Friday
            start = 8
            end = 18
        elif now.isoweekday() == 6:
            # Saturday
            start = 10
            end = 16
        elif now.isoweekday() == 7:
            # Sunday
            start = 12
            end = 16
        else:
            # All other days
            start = 8
            end = 20

        return start, end

    def give_RT_conn(self, RT):
        """
        """
        self.RT = RT

    def give_emailer(self, emailer):
        """
        """
        self.emailer = emailer

    def get_users(self):
        """
        Returns list of all users.
        """
        s = db.load_session()
        users = s.query(db.User).all()
        s.close()
        return users

    def get_ops(self):
        """
        Returns list of all users.
        """
        s = db.load_session()
        ops = s.query(db.Op).all()
        s.close()
        return ops

    def is_op(self, chatter):
        """
        Returns True / False wether or not user is op.
        """
        s = db.load_session()
        result = s.query(exists().where(db.Op.jid==chatter)).scalar()
        s.close()
        return result

    def is_user(self, chatter):
        """
        Returns True / False wether or not user is user.
        """
        s = db.load_session()
        result = s.query(exists().where(db.User.jid==chatter)).scalar()
        s.close()
        return result

    def is_authenticated(self, chatter):
        """
        Checks if chatter is admin, op or user.
        """
        if not self.is_op(chatter) and not self.is_user(chatter) and chatter != self.admin:
            return False
        return True

    def check_post_rss(self):
        if not os.path.isfile(_FEEDSFILE):
            logging.warning("No rss feeds file '%s' found." % _FEEDSFILE)
            return

        with open(_FEEDSFILE, 'r') as ffile:
            for line in ffile:
                uri = line.strip()
                feed = feedparser.parse(uri)
                sorted_entries = sorted(feed['entries'], key=lambda entry: entry['date_parsed'])
                sorted_entries.reverse()
                ndt = sorted_entries[0]['title']
                already_posted = False

                s = db.load_session()

                if s.query(exists().where(db.News.title==ndt)).scalar():
                    dup = s.query(db.News).filter_by(source=uri,title=ndt).one()

                    if dup.source == uri and dup.published > sorted_entries[0]['published_parsed']:
                        already_posted = True

                s.close()

                if not already_posted:
                    self._post(' - '.join([sorted_entries[0]['title'], sorted_entries[0]['link']]))

                    # Add this title to the list of printed titles
                    s = db.load_session()
                    s.add(db.News(title=sorted_entries[0]['title'],
                        source=uri))
                    s.commit()
                    s.close()

    def thread_proc(self):
        while not self.thread_killed:
            now = datetime.datetime.now()
            start,end = self._opening_hours(now)

            if now.minute == 0 and now.hour <= end and now.hour >= start:
                for queue in self.queues:
                    tot = self.RT.get_no_all_open(queue)
                    unowned = self.RT.get_no_unowned_open(queue)

                    if tot > 0:
                        text = "'%s' : %d unowned of total %d tickets."\
                                % (queue, unowned, tot)
                        self._post(text)

                logging.info('Printed queue statuses.')

                if now.hour == start:
                    self._post(self.godmorgen())
                if now.hour == end:
                    self._post(self.godkveld())

            if now.minute == 0 and now.hour == start:
                # Start counting
                cases_this_morning = self.RT.get_no_all_open('houston')

            if now.minute == 0 and now.hour == end:
                # Stop counting and print result
                cases_at_end = self.RT.get_no_all_open('houston')

                try:
                    solved_today = cases_at_end - cases_this_morning
                except:
                    solved_today = 0

                if solved_today != 0:
                    text = "Total change today for queue 'houston': %d (%d --> %d)" % (solved_today, cases_this_morning, cases_at_end)
                    self._post(text)

            if now.minute == 30 and now.hour == end-1:
                text = "Nå kan en begynne å tenke på kveldsrunden!"
                self._post(text)

            if now.minute == 55 and now.hour == 14:
                text = "Husk å registrere antall besøkende!"
                self._post(text)

            if now.minute == 0 and now.hour == 15:
                text = "Nå stenger KOH!"
                self._post(text)

            if now.minute == 0 and now.hour == 16 and now.isoweekday() not in [6, 7]:
                s = db.load_session()

                if not s.query(exists().where(db.Besok.date==now)).scalar():
                    text = "Det ble ikke registrert antall besøkende i dag.. Sender epost!"
                    self._post(text)

                    self.emailer.send_email('houston-forstelinje-ansatte@usit.uio.no',
                            'Glemt KOH registreringer',
                            _FORGOTTEN_KOH)

                s.close()

            # Thread for checking rss
            th = threading.Thread(target=self.check_post_rss)
            th.start()

            # Do a tick every minute
            for i in range(60):
                time.sleep(1)
                if self.thread_killed:
                    return

if __name__ == '__main__':
    logging.basicConfig(filename='rtbot.log', level=logging.DEBUG,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S')

    # Parse commandline
    parser = argparse.ArgumentParser()

    parser.add_argument('--rooms', help='Textfile with XMPP rooms one per line.',
        default='default_rooms.txt', type=str)
    parser.add_argument('--queues', help='Which queues to broadcast status from.',
        type=str)
    parser.add_argument('--broadcast', help='Should bot broadcast queue status?',
        action='store_true')

    args = parser.parse_args()

    # Gather chat credentials
    chat_username = raw_input('Chat username (remember @chat.uio.no if UiO): ')
    chat_password = getpass('Chat password: ')
    chat_admin = raw_input('JID (username@chatdomain) who can administrate bot: ')

    # Write db-path file if not exists
    if not os.path.isfile(_PREFFILE):
        dbfile = raw_input('Path to sqlite db: ')
        with open(_PREFFILE, 'w') as ofile:
            ofile.write("%s\n" % dbfile)
    import db

    # Write queues file
    filename = 'queues.txt'
    queue = []
    if args.broadcast:
        if not os.path.isfile(filename):
            # If room-file doesnt exist, ask for a room and create the file
            queue = raw_input('Queue to broadcast status from: ')

            outfile = open(filename, 'w')
            outfile.write(queue)
            outfile.write('\n')
            outfile.close()

            queue = [queue]
        else:
            # If it does exist, loop through it and list all queues
            infile = open(filename, 'r')

            for line in infile:
                queue.append(line.strip())

            infile.close()

    # Initiate bot
    bot = RTBot(chat_username, chat_password, queue, admin=chat_admin)

    # Give RT communicator
    bot.give_RT_conn(RTCommunicator())

    # Give Emailer
    bot.give_emailer(Emailer())

    # Bot nickname
    nickname = 'Anna'

    # Write rooms file
    if not os.path.isfile(args.rooms):
        # If room-file doesnt exist, ask for a room and create the file
        room = raw_input('Room to join: ')

        outfile = open(args.rooms, 'w')
        outfile.write(room)
        outfile.write('\n')
        outfile.close()

        bot.join_room(room, username=nickname)
    else:
        # If it does exist, loop through it and join all the rooms
        infile = open(args.rooms, 'r')

        for line in infile:
            bot.join_room(line.strip(), username=nickname)

        infile.close()

    if args.broadcast:
        th = threading.Thread(target=bot.thread_proc)
        bot.serve_forever(connect_callback=lambda: th.start())
        bot.thread_killed = True
    else:
        bot.serve_forever()

#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re, argparse, os, urllib, time, threading, xmpp, datetime, sqlite3
import argparse, csv, smtplib, feedparser, mimetypes, logging

from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from jabberbot import JabberBot, botcmd
from getpass import getpass
from pyRT.src.RT import RTCommunicator

"""CONSTANTS"""
_FORGOTTEN_KOH =\
"""
Hei,

det ble glemt å registrere antall besøkende med meg i dag..


hilsen Anna
"""
_EXPORT_KOH = \
"""
Hei,

her er filen med eksporterte KOH-data.


hilsen Anna
"""
_DRIFT_URL = "http://www.uio.no/tjenester/it/aktuelt/driftsmeldinger/?vrtx=feed"
_PACKAGE_TEXT = \
"""
Hei,

det har kommet en ny pakke til dere (%s) fra %s uten e-nummer. Den kan hentes i
Houston-resepsjonen.

Oppgi koden %d når du kommer for å hente den.

Eventuelle notater: %s


hilsen Anna
"""
_PACKAGE_TEXT_EN = \
"""
Hei,

det har kommet en ny pakke til dere (%s) fra %s med e-nummer %s. Den kan hentes
i Houston-resepsjonen.

Oppgi koden %d når du kommer for å hente den.

Eventuelle notater: %s


hilsen Anna
"""
_PACKAGE_KVIT = \
"""
Hei,

dette er en bekreftelse på at du (%s) hentet pakken med id %d her i
Houston-resepsjonen.


hilsen Anna
"""

"""CLASSES"""
class Emailer(object):
    def __init__(self, username=False, password=False, addr=False):
        """
        """
        self.smtp = 'smtp.uio.no'
        self.port = 465

        if not username:
            username = raw_input('Username (UiO-mail): ')
        if not password:
            password = getpass('Password (UiO-mail): ')
        if not addr:
            addr = raw_input('UiO-mail address: ')

        self.username, self.password, self.addr = username, password, addr

        try:
            server = smtplib.SMTP_SSL(self.smtp, self.port)
            server.login(self.username, self.password)
        except:
            print 'Wrong e-mailing credentials. Quitting.'
            sys.exit(0)

    def send_email(self, to, subject, text, infile=False):
        """
        """
        self.server = smtplib.SMTP_SSL(self.smtp, self.port)
        self.server.login(self.username, self.password)

        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['To'] = to
        msg['From'] = self.addr
        body_text = MIMEText(text, 'plain', 'utf-8')
        msg.attach(body_text)

        if infile:
            ctype, encoding = mimetypes.guess_type(infile)
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)

            if maintype == "text":
                fp = open(infile)
                # Note: we should handle calculating the charset
                attachment = MIMEText(fp.read(), _subtype=subtype)
                fp.close()
            elif maintype == "image":
                fp = open(infile, "rb")
                attachment = MIMEImage(fp.read(), _subtype=subtype)
                fp.close()
            elif maintype == "audio":
                fp = open(infile, "rb")
                attachment = MIMEAudio(fp.read(), _subtype=subtype)
                fp.close()
            else:
                fp = open(infile, "rb")
                attachment = MIMEBase(maintype, subtype)
                attachment.set_payload(fp.read())
                fp.close()
                encoders.encode_base64(attachment)
            attachment.add_header("Content-Disposition", "attachment", filename=infile)
            msg.attach(attachment)

        self.server.sendmail(self.addr, to, msg.as_string())

        self.server.quit()
        self.server = None

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
    def __init__(self, username, password, queues, admin, db='rtbot.db'):
        """
        queues is which queues to broadcast status from.
        """
        self.joined_rooms = []
        self.queues, self.db, self.admin = queues, db, admin

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        # Create database tables
        c.execute("""CREATE TABLE IF NOT EXISTS kohbesok
                     (date text, visitors integer)""")
        c.execute("""CREATE TABLE IF NOT EXISTS ops
                     (jid text)""")
        c.execute("""CREATE TABLE IF NOT EXISTS users
                     (jid text)""")
        c.execute("""CREATE TABLE IF NOT EXISTS rss
                     (title text)""")
        c.execute("""CREATE TABLE IF NOT EXISTS pakker
                     (recipient TEXT, sender TEXT, enummer TEXT, email TEXT, id
                     INTEGER PRIMARY KEY, notes TEXT, date_added TEXT, hentet
                     INTEGER, hentet_av TEXT, hentet_da TEXT, registrert_av TEXT,
                     registrert_hentet_av TEXT)""")

        dbconn.commit()
        dbconn.close()

        super(RTBot, self).__init__(username, password, only_direct=True)

    @botcmd
    def pakke(self, mess, args):
        """
        Brukes for å ta imot pakker, liste dem opp og markere de som hentet.
        """
        words = mess.getBody().strip().split()
        chatter, resource = str(mess.getFrom()).split('/')

        if not self.is_authenticated(chatter):
            logging.warning('%s tried to run pakke and was shown out.' % chatter)
            return "You are neither an op, admin or user. Go away!"

        parser = argparse.ArgumentParser(description='pakke command parser')
        parser.add_argument('command', choices=['ny', 'uhentede', 'hent',
            'siste'])
        parser.add_argument('--recipient', default=False)
        parser.add_argument('--sender', default=False)
        parser.add_argument('--enummer', default='')
        parser.add_argument('--id', default=False)
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

            try:
                dbconn = sqlite3.connect(self.db)
            except:
                logging.warning('%s attempt nypakke failed, no db connection.'\
                        % chatter)
                return 'Error, could not connect to database.'

            c = dbconn.cursor()
            c.execute('SELECT max(id) FROM pakker')
            rs = cursor.fetchone()

            if not rs:
                new_id = 0
            else:
                new_id = rs[0] + 1

            indata = (args.recipient, args.sender, args.enummer, args.email,
                    new_id, args.notes, dt_str, 0, '', '', chatter)
            instr = 'INSERT INTO pakker VALUES (?,?,?,?,?,?,?,?,?,?,?)'

            try:
                c.execute(instr, indata)
            except:
                dbconn.close()
                logging.warning('Adding nypakke to db failed for line\n  %s'\
                        % str(indata) )
                return 'Unable to save nypakke to database.'

            logging.info('%s added package-line\n  "%s"'\
                    % (chatter, str(indata)))

            dbconn.commit()
            dbconn.close()

            if args.enummer:
                self.emailer.send_email(args.email, 'Ny pakke fra %s, hente-id: %d'\
                        % (args.sender, new_id), _PACKAGE_TEXT_EN % (args.recipient,
                            args.sender, args.enummer, new_id, args.notes) )
            else:
                self.emailer.send_email(args.email, 'Ny pakke fra %s, hente-id: %d'\
                        % (args.sender, new_id), _PACKAGE_TEXT % (args.recipient,
                            args.sender, new_id, args.notes) )

            return 'OK, package registered with id %d and e-mail sent to %s.' % (new_id, args.email)
        elif args.command == 'uhentede':
            try:
                dbconn = sqlite3.connect(self.db)
            except:
                logging.error('Listing packages failed due to no db connection.')
                return 'Could not connect to database.'

            c = dbconn.cursor()
            c.execute('SELECT (id, date_added, sender, recipient, enummer) FROM pakker WHERE hentet=?', 0)
            rs = c.fetchall()
            dbconn.close()

            ostring = '%5s %20s %20s %20s %10s' % ('Id', 'Date recieved', 'Sender', 'Recipient', 'E-nummer')

            for pack in rs:
                ostring += '\n%5d %20s %20s %20s %10s' % pack

            logging.info('%s listed all un-fetched packages.' % chatter)
            return ostring
        elif args.command == 'hent':
            if not args.id and not args.picker:
                logging.warning('%s tried to pickup package without id or picker.'\
                                % chatter)
                return 'Need the id of the package.'

            try:
                dbconn = sqlite3.connect(self.db)
            except:
                logging.warning('Could not connect to db.')
                return 'Could not connect to db.'

            c = dbconn.cursor()
            c.execute('SELECT (email) FROM pakker WHERE id=?', ( args.id, ))
            rs = c.fetchone()
            dbconn.close()

            if not rs:
                logging.warning('%s tried to pickup non-existing package.'\
                        % chatter)
                return 'No such package.'

            now = datetime.datetime.now()
            dt_str = datetime.datetime.strftime(now, '%Y-%m-%d %H:%M:%S')

            try:
                dbconn = sqlite3.connect(self.db)
            except:
                logging.warning('Could not connect to db.')
                return 'Could not connect to db.'

            c = dbconn.cursor()
            c.execute("""UPDATE pakker SET
                         hentet=?,hentet_av=?,hentet_da=?,registrert_hentet_av=?
                         WHERE id=?""", ( 1, args.picker, dt_str, chatter))
            dbconn.commit()
            dbconn.close()

            self.emailer.send_email(args.email, 'Ny pakke fra %s, hente-id: %d'\
                    % (args.sender, new_id), _PACKAGE_KVIT % (args.picker,
                        args.id) )

            return 'OK, pakke med id %d registrert som hentet av %s.' % (args.id, args.picker)
        elif args.command == 'siste':
            try:
                dbconn = sqlite3.connect(self.db)
            except:
                logging.warning('Could not connect to db.')
                return 'Could not connect to db.'

            c = dbconn.cursor()
            c.execute('SELECT (id, date_added, sender, recipient, enummer) FROM pakker ORDER BY date_added')
            rs = c.fetchall()
            dbconn.close()

            ostring = '%5s %20s %20s %20s %10s' % ('Id', 'Date recieved', 'Sender', 'Recipient', 'E-nummer')

            counter = 1
            for pack in rs:
                ostring += '\n%5d %20s %20s %20s %10s' % pack
                counter += 1
                if counter == 10:
                    break

            logging.info('%s listed last 10 packages.' % chatter)
            return ostring

    @botcmd
    def useradmin(self, mess, args):
        """
        Can be used to set user permissions and add users.
        """
        words = mess.getBody().strip().split()
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()
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
            dbconn.close()
            logging.info('%s used bad syntax for useradmin.' % chatter)
            return 'Usage: useradd op/user/list --jid username@domain'

        c.execute('SELECT * FROM users')
        users = c.fetchall()

        if args.level == 'op':
            if self.is_op(args.jid):
                dbconn.close()
                return '%s is already an op.' % args.jid

            t = ( args.jid, )
            c.execute('INSERT INTO ops VALUES (?)', t)
            dbconn.commit()
            dbconn.close()

            logging.info('%s made %s an op.' % (chatter, args.jid))

            return 'OK, made %s an op.' % args.jid
        elif args.level == 'user':
            if self.is_user(args.jid):
                dbconn.close()
                return '%s is already a user.' % args.jid

            t = ( args.jid, )
            c.execute('INSERT INTO users VALUES (?)', t)
            dbconn.commit()

            logging.info('%s made %s a user.' % (chatter, args.jid))

            dbconn.close()
            return 'OK, made %s a user.' % args.jid
        elif args.level == 'list':
            ostring = '--- OPS: ---'

            for op in self.get_ops():
                ostring += '\n* %s' % op

            ostring += '\n--- USERS: ---'

            c.execute('SELECT * FROM users')
            users = c.fetchall()

            for user in self.get_users():
                ostring += '\n* %s' % user

            logging.info('%s listed all users and ops.' % chatter)
            dbconn.close()
            return ostring

    @botcmd
    def listkoh(self, mess, args):
        """
        Lists last 10 entries in kos table.
        """
        chatter, resource = str(mess.getFrom()).split('/')
        now = datetime.datetime.now()
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        if not self.is_user(chatter) and not self.is_op(chatter):
            dbconn.close()
            logging.info('%s, not op nor user tried to run kohbesok.' % chatter)
            return 'You are neither a registered user or op, go away!'

        output = ""
        counter = 0
        for row in c.execute('SELECT * FROM kohbesok ORDER BY date DESC'):
            output += '%10s: %4d\n' % (row[0], int(row[1]))
            counter += 1

            if counter == 10:
                break

        logging.info('%s listed last 10 koh visits.' % chatter)

        dbconn.close()
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
        words = mess.getBody().strip().split()
        now = datetime.datetime.now()
        d = datetime.datetime.strftime(now, '%Y-%m-%d')
        chatter, resource = str(mess.getFrom()).split('/')

        parser = argparse.ArgumentParser(description='kohbesok command parser')
        parser.add_argument('command', choices=['register', 'edit'],
                help='What to do.')
        parser.add_argument('visitors', type=int, help='Number of visitors.')
        parser.add_argument('--date', help='Can override todays date.',
                default=d)

        try:
            args = parser.parse_args(words[1:])
            datetime.datetime.strptime(args.date, '%Y-%m-%d')
        except:
            logging.info('%s used bad syntax for kohbesok.' % chatter)
            return 'Usage: kohbesok register/edit visitors [--date YYYY-mm-dd]'

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        if not self.is_user(chatter) and not self.is_op(chatter):
            dbconn.close()
            logging.info('%s, not op nor user tried to run kohbesok.' % chatter)
            return 'You are neither a registered user or op, go away!'

        if args.command == 'register':
            # Check if already registered this date
            t = ( args.date, )
            c.execute('SELECT * FROM kohbesok WHERE date=?', t)
            if c.fetchone():
                dbconn.close()
                return "This date is already registered."

            t = ( args.date, args.visitors )

            c.execute('INSERT INTO kohbesok VALUES (?,?)', t)
            dbconn.commit()

            logging.info('%s registered %d koh-visitors for %s' \
                    % (chatter, args.visitors, args.date))

            dbconn.close()

            return 'OK, registered %d for %s.' % (args.visitors, args.date)
        elif args.command == 'edit':
            if not self.is_op(chatter):
                dbconn.close()
                logging.info('%s (not op) tried to edit koh post.' % chatter)
                return "You are not an op and cannot edit."

            # Update an existing row
            c.execute('SELECT * FROM kohbesok WHERE date=?', (args.date, ))
            rs = c.fetchone()
            if not rs:
                dbconn.close()
                logging.info('%s tried to edit non-existing data' % chatter)
                return "There is no data on this date yet."

            old_value = rs[1]

            c.execute('UPDATE kohbesok SET visitors=? where date=?',
                    (args.visitors, args.date))
            dbconn.commit()

            logging.info('%s changed %d to %d for %s' % (chatter, old_value,
                args.visitors, args.date))

            dbconn.close()

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
        return "God morgen, førstelinja!"

    def godkveld(self):
        """
        Si god kveld.
        """
        return "God kveld 'a! Nå har dere fortjent litt fri :)"

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

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        logging.info('Finding all kohbesok between %s and %s' % (args.start, args.end))

        writer.writerow(['Date', 'Visitors'])
        for row in c.execute('SELECT * FROM kohbesok WHERE date BETWEEN "%s" AND "%s" ORDER BY date' % (args.start, args.end)):
            writer.writerow([row[0], row[1]])

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

    def muc_join_room(self, room, *args, **kwargs):
        """
        Need a list of all joined rooms.
        """
        self.joined_rooms.append(room)
        super(RTBot, self).muc_join_room(room, *args, **kwargs)

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
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        c.execute('SELECT * FROM users')
        users = [elm[0] for elm in c.fetchall()]

        dbconn.close()
        return users

    def get_ops(self):
        """
        Returns list of all users.
        """
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        c.execute('SELECT * FROM ops')
        ops = [elm[0] for elm in c.fetchall()]

        dbconn.close()
        return ops

    def is_op(self, chatter):
        """
        Returns True / False wether or not user is op.
        """
        if chatter in self.get_ops():
            return True
        return False

    def is_user(self, chatter):
        """
        Returns True / False wether or not user is user.
        """
        if chatter in self.get_users():
            return True
        return False

    def is_authenticated(self, chatter):
        """
        Checks if chatter is admin, op or user.
        """
        if not self.is_op(chatter) and not self.is_user(chatter) and chatter != self.admin:
            return False
        return True

    def thread_proc(self):
        spam_upper = 100
        utskrift_tot = self.RT.get_no_all_open('houston-utskrift')

        sendspam = False
        sendutskrift = False

        while not self.thread_killed:
            logging.info('Tick')

            now = datetime.datetime.now()
            start,end = self._opening_hours(now)

            if now.minute == 0 and now.hour <= end and now.hour >= start:
                for queue in self.queues:
                    tot = self.RT.get_no_all_open(queue)
                    unowned = self.RT.get_no_unowned_open(queue)

                    if queue == 'spam-suspects' and tot > spam_upper:
                        sendspam = True

                    if queue == 'houston-utskrift' and tot > utskrift_tot:
                        sendutskrift = True
                        utskrift_tot = tot

                    text = "'%s' : %d unowned of total %d tickets."\
                            % (queue, unowned, tot)
                    self._post(text)

                logging.info('Printed queue statuses.')

                if now.hour == start:
                    self._post(self.godmorgen())
                if now.hour == end:
                    self._post(self.godkveld())

            if sendspam and now.hour != end:
                text = "Det er over %d saker i spam-køen! På tide å ta dem?" % spam_upper
                self._post(text)
                sendspam = False

            if sendutskrift and now.hour != end:
                text = "Det har kommet en ny sak i 'houston-utskrift'!"
                self._post(text)
                sendutskrift = False

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

            if now.minute == 0 and now.hour == 16 and now.isoweekday() not in [6, 7]:
                # Mail boss if KOH visits not registered
                dbconn = sqlite3.connect(self.db)
                c = dbconn.cursor()

                # Count if there is a registration today
                d = datetime.datetime.strftime(now, '%Y-%m-%d')
                t = (d,)
                c.execute('SELECT * FROM kohbesok WHERE date=?', (d, ) )
                rs = c.fetchone()

                if not rs:
                    # No data registered today, send notification
                    self.emailer.send_email('b.e.brakken@usit.uio.no', 'Glemt KOH registreringer i dag',
                            _FORGOTTEN_KOH)
                    self.emailer.send_email('rune.ersdal@usit.uio.no', 'Glemt KOH registreringer i dag',
                            _FORGOTTEN_KOH)

                dbconn.close()

            # After this processes taking time can be put
            feed = feedparser.parse(_DRIFT_URL)
            sorted_entries = sorted(feed['entries'], key=lambda entry: entry['date_parsed'])
            sorted_entries.reverse()
            newest_drift_title = sorted_entries[0]['title']
            already_posted = False

            try:
                dbconn = sqlite3.connect(self.db)
                c = dbconn.cursor()

                c.execute('SELECT * FROM rss WHERE title=?',
                        ( newest_drift_title, ) )
                rs = c.fetchone()

                dbconn.close()

                if rs:
                    already_posted = True
            except:
                logging.warning('Could not check for newest title in rss table.')

            if not already_posted:
                self._post('NY DRIFTSMELDING: %s' % ' - '.join([sorted_entries[0]['title'], sorted_entries[0]['link']]))

                # Add this title to the list of printed titles
                try:
                    dbconn = sqlite3.connect(self.db)
                    c = dbconn.cursor()

                    c.execute('INSERT INTO rss VALUES (?)',
                            ( sorted_entries[0]['title'], ))

                    dbconn.commit()
                    dbconn.close()
                except:
                    logging.warning('Could not connect to db for rss title storage.')

            # Do a tick every minute
            for i in range(60):
                time.sleep(1)
                if self.thread_killed:
                    return

if __name__ == '__main__':
    logging.basicConfig(filename='rtbot.log', level=logging.INFO,
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

        bot.muc_join_room(room, username=nickname)
    else:
        # If it does exist, loop through it and join all the rooms
        infile = open(args.rooms, 'r')

        for line in infile:
            bot.muc_join_room(line.strip(), username=nickname)

        infile.close()

    if args.broadcast:
        th = threading.Thread(target=bot.thread_proc)
        bot.serve_forever(connect_callback=lambda: th.start())
        bot.thread_killed = True
    else:
        bot.serve_forever()

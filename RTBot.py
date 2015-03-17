#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re, argparse, os, urllib, time, threading, xmpp, datetime, sqlite3
import argparse, csv, smtplib, feedparser, mimetypes

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

"""CLASSES"""
class Emailer(object):
    def __init__(self, username, password, addr):
        """
        """
        self.smtp = 'smtp.uio.no'
        self.port = 465
        self.username = username
        self.password = password
        self.addr = addr

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
    def __init__(self, username, password, queues, db='rtbot.db'):
        """
        queues is which queues to broadcast status from.
        """
        self.joined_rooms = []
        self.queues = queues
        self.db = db

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        # Create KOH table if not exists
        c.execute("""CREATE TABLE IF NOT EXISTS kohbesok
                     (date text, visitors integer)""")

        dbconn.close()

        super(RTBot, self).__init__(username, password, only_direct=True)

    @botcmd
    def listkoh(self, mess, args):
        """
        Lists last 10 entries in kos table.
        """
        now = datetime.datetime.now()
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        output = ""
        counter = 0
        for row in c.execute('SELECT * FROM kohbesok ORDER BY date'):
            output += '%10s: %4d\n' % (row[0], int(row[1]))
            counter += 1

            if counter == 10:
                break

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

        parser = argparse.ArgumentParser(description='kohbesok command parser')
        parser.add_argument('command', choices=['register', 'edit'],
                help='What to do.')
        parser.add_argument('visitors', type=int, help='Number of visitors.')
        parser.add_argument('--date', help='Can override todays date.',
                default=d)

        try:
            args = parser.parse_args(words[1:])
        except:
            return 'Usage: kohbesok register/edit visitors [--date YYYY-mm-dd]'

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

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

            logging.info('Inserted %d koh-visitors for %s.' \
                    % (args.visitors, args.date))

            dbconn.close()

            return 'OK, registered %d for %s.' % (args.visitors, args.date)
        elif args.command == 'edit':
            logging.info('Edit kohbesok request from %s.' % mess.getFrom())

            chatter,resource = mess.getFrom().split('/')
            if chatter not in ['benedebr@chat.uio.no',
                    'rersdal@chat.uio.no', 'olsen@chat.uio.no']:
                return "You are not an op."

            # Update an existing row
            c.execute('SELECT * FROM kohbesok WHERE date=?', (d, ))
            rs = c.fetchone()
            if not rs:
                dbconn.close()
                return "There is no data on this date yet."

            old_value = rs[1]

            c.execute('UPDATE kohbesok SET visitors=? where date ="?"',
                    (args.visitors, args.date))
            dbconn.commit()
            logging.info('kohbesok entry updated.')

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

        logging.info('Finding all kohbesok between %s and %s' % (args.start,
            args.end))

        writer.writerow(['Date', 'Visitors'])
        for row in c.execute('SELECT * FROM kohbesok WHERE date BETWEEN "%s" AND "%s" ORDER BY date' % (args.start, args.end)):
            logging.info(row)
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

    def thread_proc(self):
        spam_upper = 100
        utskrift_tot = self.RT.get_no_all_open('houston-utskrift')

        sendspam = False
        sendutskrift = False

        # At startup, save last driftsmelding
        feed = feedparser.parse(_DRIFT_URL)
        sorted_entries = sorted(feed['entries'], key=lambda entry: entry['date_parsed'])
        sorted_entries.reverse()
        last_drift_title = sorted_entries[0]['title']

        while not self.thread_killed:
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

                if solved_today != 0 and spam_del_today != 0:
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

            if newest_drift_title != last_drift_title:
                self._post('NY DRIFTSMELDING: %s' % ' - '.join([sorted_entries[0]['title'], sorted_entries[0]['link']]))
                last_drift_title = sorted_entries[0]['title']

            # Do a tick every minute
            for i in range(60):
                time.sleep(1)
                if self.thread_killed:
                    return

if __name__ == '__main__':
    # Just for connection info ++
    import logging
    logging.basicConfig(level=logging.INFO)

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
    bot = RTBot(chat_username, chat_password, queue)

    # Give the RT communicator class to the bot
    RT = RTCommunicator()
    bot.give_RT_conn(RT)

    email_password = getpass('Email password for %s: ' % RT.user)
    addr = raw_input('Email address: ')
    bot.give_emailer(Emailer(RT.user, email_password, addr))

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

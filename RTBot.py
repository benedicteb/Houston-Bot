#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re, argparse, os, urllib, time, threading, xmpp, datetime, sqlite3
import argparse, csv, smtplib
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
        self.server = smtplib.SMTP_SSL(self.smtp, self.port)

    def send_email(self, to, subject, text, attachment=False):
        """
        """
        self.server.login(self.username, self.password)

        msg = MIMEMultipart()
        msg['Subject'] = subject
        msg['To'] = to
        msg['From'] = self.addr
        body_text = MIMEText(text, 'plain', 'utf-8')
        msg.attach(body_text)

        self.server.sendmail(self.addr, to, msg.as_string())

        self.server.quit()

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
                     (date text, visitors real)""")

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
            output += '%10s: %4d' % (row[0], int(row[1]))
            counter += 1

            if counter == 10:
                break

        dbconn.close()
        return output

    @botcmd
    def kohbesok(self, mess, args):
        """
        """
        words = mess.getBody().strip().split()
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
            return 'Bad command.'

        now = datetime.datetime.now()
        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        if args.command == 'register':
            # Check if already registered this date
            t = (d,)
            c.execute('SELECT * FROM kohbesok WHERE date=?', t)
            if c.fetchone():
                dbconn.close()
                return "This date is already registered."

            t = ( d, visitors )
            c.execute('INSERT INTO kohbesok VALUES (?,?)', t)
            dbconn.commit()
            logging.info('kohbesok entry inserted.')
            dbconn.close()

            return 'OK, registered %d for today, %s.' % (visitors, d)
        elif args.command == 'edit':
            c.execute('SELECT * FROM kohbesok WHERE date=?', t)
            rs = c.fetchone()
            if not rs:
                dbconn.close()
                return "There is no data on this date yet."

            old_value = rs[1]

            t = (d,)
            c.execute('UPDATE kohbesok SET visitors=? where date ="?"',
                    (args.visitors, args.date))
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
        parser.add_argument('start', 'From-date.')
        parser.add_argument('end', 'To-date.')
        parser.add_argument('email', 'E-mail to send file to.')

        try:
            args = parser.parse_args(mess.getBody().strip().split())
        except:
            return 'Usage: exportkoh start-date(YYYY-mm-dd) end-date email'

        filename = 'koh.csv'

        if os.path.isfile(filename):
            os.remove(filename)

        csvfile = open('koh.csv', 'wb')
        writer = csv.writer(csvfile, delimiter=' ',
                quotechar='|', quoting=csv.QUOTE_MINIMAL)

        dbconn = sqlite3.connect(self.db)
        c = dbconn.cursor()

        logging.info('Finding all kohbesok between %s and %s' % (args.start,
            args.end))

        writer.writerow(['Date', 'Visitors'])
        for row in c.execute('SELECT * FROM kohbesok WHERE date BETWEEN %s AND %s ORDER BY date' % (args.start, args.end)):
            writer.writerow([row[0], row[1]])

        return 'File written!'

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
            message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
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
                spam_this_morning = self.RT.get_no_all_open('spam-suspects')

            if now.minute == 0 and now.hour == end:
                # Stop counting and print result
                cases_at_end = self.RT.get_no_all_open('houston')
                spam_at_end = self.RT.get_no_all_open('spam-suspects')

                try:
                    solved_today = cases_this_morning - cases_at_end
                    spam_del_today = spam_this_morning - spam_at_end
                except:
                    solved_today = 0
                    spam_del_today = 0

                if solved_today != 0 and spam_del_today != 0:
                    text = "%d cases were resolved today in 'houston'" % solved_today
                    self._post(text)

                    text = "%d spam were deleted today from 'spam-suspects'" % spam_del_today
                    self._post(text)

            if now.minute == 30 and now.hour == end-1:
                text = "Nå kan en begynne å tenke på #kveldsrunden!"
                self._post(text)

            if now.minute == 0 and now.hour == 16 and now.isoweekday() not in [6, 7]:
                # Mail boss if KOH visits not registered
                dbconn = sqlite3.connect(self.db)
                c = dbconn.cursor()

                # Count if there is a registration today
                d = datetime.datetime.strftime(now, '%Y-%m-%d')
                t = (d,)
                counter = 0
                for row in c.execute('SELECT * FROM kohbesok WHERE date=?', t):
                    counter += 1

                dbconn.close()

                if counter == 0:
                    self.emailer.send_email('b.e.brakken@usit.uio.no', 'Glemt KOH registreringer i dag',
                            _FORGOTTEN_KOH)

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

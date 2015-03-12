#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re, argparse, os, urllib, time, threading, xmpp, datetime
from jabberbot import JabberBot, botcmd
from getpass import getpass
from pyRT.src.RT import RTCommunicator

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

        # Hack for not replying to private messages. This is for security
        # reasons, since general RT access is bad.
        message_type = mess.getType()
        if message_type == 'chat':
            mess.setBody('private')
            return super(MUCJabberBot, self).callback_message(conn, mess)

        if re.search('#morgenru', message):
            mess.setBody('morgenrutiner')
            return super(MUCJabberBot, self).callback_message(conn, mess)
        if re.search('#kveldsru', message):
            mess.setBody('kveldsrutiner')
            return super(MUCJabberBot, self).callback_message(conn, mess)

        tickets = re.findall(self.direct_message_re, message)
        if len(tickets) != 0:
            mess.setBody('rtinfo %s' % tickets[0])
            return super(MUCJabberBot, self).callback_message(conn, mess)
        else:
            return

class RTBot(MUCJabberBot):
    def __init__(self, username, password, queues):
        """
        queues is which queues to broadcast status from.
        """
        self.joined_rooms = []
        self.queues = queues
        super(RTBot, self).__init__(username, password, only_direct=True)

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

    def godmorgen(self, mess, args):
        """
        Si god morgen.
        """
        return "God morgen, førstelinja!"

    def godkveld(self, mess, args):
        """
        Si god kveld.
        """
        return "God kveld!"

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

    def give_RT_conn(self, RT):
        """
        """
        self.RT = RT

    def thread_proc(self):
        spam_upper = 100
        utskrift_tot = self.RT.get_no_all_open('houston-utskrift')

        sendspam = False
        sendutskrift = False

        while not self.thread_killed:
            now = datetime.datetime.now()

            # Opening hours
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

            if now.minute == 0 and now.hour <= end and now.hour >= start:
                for room in self.joined_rooms:
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
                        message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)

                        self.conn.send(message)

                    if now.hour == end:
                        text = "God kveld!"
                        message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                        self.conn.send(message)

                    if now.hour == start:
                        text = "God morgen!"
                        message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                        self.conn.send(message)

            if sendspam and now.hour != end:
                for room in self.joined_rooms:
                    text = "Det er over %d saker i spam-køen! På tide å ta dem?" % spam_upper
                    message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                    self.conn.send(message)
                sendspam = False

            if sendutskrift and now.hour != end:
                for room in self.joined_rooms:
                    text = "Det har kommet en ny sak i 'houston-utskrift'!"
                    message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                    self.conn.send(message)
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

                for room in self.joined_rooms:
                    text = "%d cases were resolved today in 'houston'" % solved_today
                    message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                    self.conn.send(message)

                    text = "%d spam were deleted today from 'spam-suspects'" % spam_del_today
                    message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                    self.conn.send(message)

            if now.minute == 30 and now.hour == end-1:
                for room in self.joined_rooms:
                    text = "Nå kan en begynne å tenke på #kveldsrunden!"
                    message = "<message to='{0}' type='groupchat'><body>{1}</body></message>".format(room, text)
                    self.conn.send(message)

            # Do a tick every minute
            for i in range(60):
                time.sleep(1)

if __name__ == '__main__':
    # Just for connection info ++
    import logging
    logging.basicConfig(level=logging.DEBUG)

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

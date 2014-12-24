#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re, argparse, os, urllib, time, threading
from jabberbot import JabberBot, botcmd
from getpass import getpass

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

        tickets = re.findall(self.direct_message_re, message)
        if len(tickets) != 0:
            mess.setBody('rtinfo %s' % tickets[0])
            return super(MUCJabberBot, self).callback_message(conn, mess)
        else:
            return

class RTBot(MUCJabberBot):
    @botcmd
    def rtinfo(self, mess, args):
        """
        Tells you some RT info for given ticket id.
        """
        ticket_id = str(mess.getBody().split()[-1])
        return self.RT.rt_string(ticket_id)

    @botcmd
    def private(self, mess, args):
        """
        Tells user that this bot cannot communicate via private chat.
        """
        return "Sorry, I'm not allowed to talk privately."

    @botcmd
    def broadcast(self, mess, args):
        """
        Broadcast message about number of unowned open tickets every hour.
        """
        where = 'houston'
        return 'There are %d unowned tickets in queue %s.' \
                        % (self.RT.get_no_unowned(where), where)

    def give_RT_conn(self, RT):
        """
        """
        self.RT = RT

    def thread_proc(self):
        while not self.thread_killed:
            self.broadcast('', '')
            for i in range(60*60):
                time.sleep(1)
                if self.thread_killed:
                    return

class RTCommunicator(object):
    """
    Class just needed for storing username / password.
    """
    def __init__(self, username=False, password=False):
        """
        username, password: For RT
        """
        # Gather credentials if not given
        if not username and not password:
            self.user = raw_input('RT Username: ')
            self.password = getpass('RT Password: ')
        else:
            self.user, self.password = username, password

    def rt_string(self, ticket_id):
        """
        Returns string describing info og given RT ticket id.
        """
        urlbase = 'https://rt.uio.no/REST/1.0/ticket/%s/show' % ticket_id
        getlink = urlbase + '/' + '?user=' + self.user + '&pass=' + self.password

        output = urllib2.urlopen(getlink).read()

        subject = re.findall(r'^Subject: (.+)$', output, re.MULTILINE)[0]
        owner = re.findall(r'^Owner: (.+)$', output, re.MULTILINE)[0]
        status = re.findall(r'^Status: (.+)$', output, re.MULTILINE)[0]

        # Requestors can be empty
        try:
            requestors = re.findall(r'^Requestors: (.+)$', output, re.MULTILINE)[0]
        except:
            requestors = '(no requestors)'

        link_to_ticket = 'https://rt.uio.no/Ticket/Display.html?id=%s' % ticket_id

        return ' - '.join([subject, owner, status, requestors, link_to_ticket])

    def get_all_tickets(self, queue):
        """
        Returns all tickets open or new from given queue not including "TIL
        INFO" cases.
        """
        query = "Owner = 'Nobody' AND (Status = 'new' OR Status = 'open')"
        query += " AND Queue='%s' AND Subject NOT LIKE 'TIL INFO'" % queue

        params = {
            'user' : self.user,
            'pass' : self.password,
            'query' : query
        }

        urlbase = "https://rt.uio.no/REST/1.0/search/ticket?"
        full_link = ''.join([urlbase, urllib.urlencode(params)])

        output = urllib2.urlopen(full_link).read()

        sr = r'^(\d+): (.*)$'

        return re.findall(sr, output, re.MULTILINE)

    def get_no_unowned(self, queue):
        """
        Returns int representing number of unowned open tickets not including
        til info cases in given queue.
        """
        return len(self.get_all_tickets(queue))

if __name__ == '__main__':
    # Just for connection info ++
    import logging
    logging.basicConfig(level=logging.DEBUG)

    # Parse commandline
    parser = argparse.ArgumentParser()

    parser.add_argument('--rooms', help='Textfile with XMPP rooms one per line.',
        default='default_rooms.txt', type=str)

    args = parser.parse_args()

    # Gather chat credentials
    chat_username = raw_input('Chat username (remember @chat.uio.no if UiO): ')
    chat_password = getpass('Chat password: ')

    # Initiate bot
    bot = RTBot(chat_username, chat_password, only_direct=True)

    # Give the RT communicator class to the bot
    RT = RTCommunicator()
    bot.give_RT_conn(RT)

    if not os.path.isfile(args.rooms):
        # If room-file doesnt exist, ask for a room and create the file
        room = raw_input('Room to join: ')

        outfile = open(args.rooms, 'w')
        outfile.write(room)
        outfile.close()

        bot.muc_join_room(room)
    else:
        # If it does exist, loop through it and join all the rooms
        infile = open(args.rooms, 'r')

        for line in infile:
            bot.muc_join_room(line.strip())

        infile.close()

    th = threading.Thread(target=bot.thread_proc)
    bot.serve_forever(connect_callback=lambda: th.start())
    bot.thread_killed = True

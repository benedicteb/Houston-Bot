#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import urllib2, re
from jabberbot import JabberBot, botcmd
from getpass import getpass

"""CLASSES"""
class MUCJabberBot(JabberBot):
    ''' Add features in JabberBot to allow it to handle specific
    caractheristics of multiple users chatroom (MUC). '''
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
        self.direct_message_re = r'\s+#(\d+)'

    def callback_message(self, conn, mess):
        message = mess.getBody()
        if not message:
            return

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

    def give_RT_conn(self, RT):
        self.RT = RT

class RTCommunicator(object):
    """
    Class just needed for storing username / password.
    """
    def __init__(self, username, password):
        """
        username, password: For RT
        """
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
        requestors = re.findall(r'^Requestors: (.+)$', output, re.MULTILINE)[0]
        link_to_ticket = 'https://rt.uio.no/Ticket/Display.html?id=%s' % ticket_id

        return ' - '.join([subject, owner, status, requestors, link_to_ticket])

if __name__ == '__main__':
    # Just for connection info ++
    import logging
    logging.basicConfig(level=logging.DEBUG)

    rt_username = raw_input('RT Username: ')
    rt_password = getpass('RT Password: ')
    chat_username = raw_input('Chat username (remember @chat.uio.no if UiO): ')
    chat_password = getpass('Chat password: ')
    room = raw_input('Room to join: ')

    bot = RTBot(chat_username, chat_password, only_direct=True)

    RT = RTCommunicator(rt_username, rt_password)
    bot.give_RT_conn(RT)

    bot.muc_join_room(room)
    bot.serve_forever()

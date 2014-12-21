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
class RTBot(JabberBot):
    def __init__(self, username, password, RT):
        super(RTBot, self).__init__(username, password)
        self.RT = RT

    @botcmd
    def rtinfo(self, mess, args):
        """
        Tells you some RT info for given ticket id.
        """
        ticket_id = str(mess.getBody().split()[-1])
        return self.RT.rt_string(ticket_id)

    @botcmd
    def test(self, mess, args):
        """
        Test command to check that the bot is there.
        """
        return 'test: ' + args

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

    RT = RTCommunicator(rt_username, rt_password)
    bot = RTBot(chat_username, chat_password, RT)
    bot.serve_forever()

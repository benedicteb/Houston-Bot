#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Simple XMPP bot used to get information from the RT (Request Tracker) API.

@author Benedicte Emilie Brækken
"""
import smtplib, mimetypes

from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText

from getpass import getpass

class Emailer(object):
    def __init__(self, username=False, password=False):
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

        self.username, self.password = username, password
        self.addr = self.username + '@ulrik.uio.no'

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

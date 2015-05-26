#!/usr/bin/env python
# *-* encoding: utf-8 *-*
"""
Database schema.

@author Benedicte Emilie Brækken
"""
from sqlalchemy import Column, DateTime, String, Integer, Boolean, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

import datetime
import sys
import os

from RTBot import read_prefs

# Make sure settings are there
_PREFFILE = 'prefs.txt'
if not os.path.isfile(_PREFFILE):
    print "%s\n  No prefs file." % e
    sys.exit(0)
_PREFS = read_prefs(_PREFFILE)

engine = create_engine('sqlite:///%s' % _PREFS['dbpath'])
Base = declarative_base()

class Besok(Base):
    __tablename__ = 'kohbesok'

    visitors = Column(Integer, nullable=False)
    date = Column(DateTime, nullable=False, default=datetime.datetime.utcnow,
            primary_key=True)

class Op(Base):
    __tablename__ = 'ops'

    jid = Column(String, nullable=False, primary_key=True)

class User(Base):
    __tablename__ = 'users'

    jid = Column(String, nullable=False, primary_key=True)

class News(Base):
    __tablename__ = 'rss'

    id = Column(Integer, primary_key=True)

    title = Column(String, nullable=False)
    published = Column(DateTime, nullable=False,
            default=datetime.datetime.utcnow)
    source = Column(String, nullable=False)

class Package(Base):
    __tablename__ = 'pakker'

    id = Column(Integer, primary_key=True)

    hentet_da = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    date_added = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    hentet = Column(Boolean, nullable=False, default=False)

    recipient = Column(String, nullable=False)
    sender = Column(String, nullable=False)
    email = Column(String, nullable=False)
    registrert_av = Column(String, nullable=False)

    notes = Column(String)
    enummer = Column(String)
    hentet_av = Column(String)
    registrert_hentet_av = Column(String)

Base.metadata.create_all(engine)

def load_session():
    return sessionmaker(bind=engine)()

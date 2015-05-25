#!/usr/bin/env python
"""
Takes all kohbesok from given arg 1 and adds to db governed på db file.

@author benedebr
"""
import db
import sqlite3
import datetime
import sys

conn = sqlite3.connect(sys.argv[1])
c = conn.cursor()

c.execute('select * from kohbesok;')
rs = c.fetchall()

s = db.load_session()

for r in rs:
    date = datetime.datetime.strptime(r[0], '%Y-%m-%d')
    s.add(db.Besok(date=date, visitors=r[1]))
    s.commit()

s.close()

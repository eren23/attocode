# SQL injection patterns — true positives
# Each line annotated with # expect: should trigger matching rules

import sqlite3

def bad_format_string(user_id):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)  # expect: security/python_sql_format_string

def bad_fstring(table):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute(f"SELECT * FROM {table}")  # expect: security/python_sql_fstring

def bad_concat(name):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute("SELECT * FROM users WHERE name = '" + name + "'")  # expect: security/python_sql_concat

def bad_format_method(email):
    cursor = sqlite3.connect(":memory:").cursor()
    cursor.execute("SELECT * FROM users WHERE email = '{}'".format(email))  # expect: security/python_sql_format_string

import sqlite3

# Connect to the SQLite database file
conn = sqlite3.connect("shesafe.db")
cursor = conn.cursor()

# List all tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
print("Tables:", tables)

# Fetch incidents
cursor.execute("SELECT * FROM incidents;")
rows = cursor.fetchall()
for row in rows:
    print(row)

conn.close()
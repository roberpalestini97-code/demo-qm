"""Bandeja de salida en SQLite: si se corta el enlace, los mensajes esperan acá y salen en orden al volver."""
import os
import sqlite3


class Outbox:
    def __init__(self, path):
        if path != ":memory:":
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY, topic TEXT, payload TEXT)")
        self.db.commit()

    def put(self, topic, payload):
        self.db.execute("INSERT INTO outbox (topic, payload) VALUES (?, ?)", (topic, payload))
        self.db.commit()

    def peek(self, limit=50):
        return self.db.execute("SELECT id, topic, payload FROM outbox ORDER BY id LIMIT ?", (limit,)).fetchall()

    def ack(self, ids):
        self.db.executemany("DELETE FROM outbox WHERE id = ?", [(i,) for i in ids])
        self.db.commit()

    def __len__(self):
        return self.db.execute("SELECT count(*) FROM outbox").fetchone()[0]

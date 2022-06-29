import os
import logging
import time
import pathlib
import sqlite3
import datetime

import requests


DATABASE = pathlib.Path(".") / "cr.db"
API_TOKEN = os.getenv("CLASH_ROYALE_API_TOKEN")
assert API_TOKEN, "undefined API TOKEN"

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

log.addHandler(ch)


class dbopen:
    """Simple Contex Manager for sqlite3 databases.
    Credit to https://gist.github.com/miku/6522074
    """

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.conn = sqlite3.connect(self.path)
        self.cursor = self.conn.cursor()
        return self.cursor

    def __exit__(self, exc_class, exc, traceback):
        self.conn.commit()
        self.conn.close()


def create_db():

    log.info("Creating new database")

    with dbopen(DATABASE) as c:

        # Create Players Table
        c.execute("CREATE TABLE players (update_time TEXT, tag TEXT PRIMARY KEY)")
        log.debug("Created players table")

        # Create Decks Table
        c.execute(
            (
                "CREATE TABLE decks ("
                "deck_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                "card_1 INTEGER, card_2 INTEGER, card_3 INTEGER, card_4 INTEGER, "
                "card_5 INTEGER, card_6 INTEGER, card_7 INTEGER, card_8 INTEGER) "
            )
        )
        log.debug("Created deck table")

        # Create Battles Table
        c.execute(
            (
                "CREATE TABLE battles ("
                "battle_id INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT, "
                "time TEXT, winner INTEGER, "
                "tag_1 TEXT, trophies_1 INTEGER, king_hp_1 INTEGER, "
                "princess_1_hp_1 INTEGER, princess_2_hp_1 INTEGER, "
                "deck_1 INTEGER, "
                "tag_2 TEXT, trophies_2 INTEGER, king_hp_2 INTEGER, "
                "princess_1_hp_2 INTEGER, princess_2_hp_2 INTEGER, "
                "deck_2 INTEGER, "
                "FOREIGN KEY(deck_1) REFERENCES decks(deck_id), "
                "FOREIGN KEY(deck_2) REFERENCES decks(deck_id)) "
            )
        )
        log.debug("Created battles table")


def out_player(outdated=3600):

    # I know that this function is vulnerable to SQL injection attacks but
    # I cannot figure out a way to make parameter substitution work inside
    # datetime function

    with dbopen(DATABASE) as c:
        player = c.execute(
            (
                f"SELECT tag FROM players WHERE ( "
                f"update_time < datetime('now','+{outdated} seconds') OR "
                f"update_time is NULL ) "
                f"ORDER BY update_time "
            )
        ).fetchone()

    return player[0] if player is not None else None


def in_player(player, update_time=None):

    values = [update_time, player]

    with dbopen(DATABASE) as c:
        c.execute("INSERT OR IGNORE INTO players VALUES (?, ?)", values)
        if update_time is not None:
            c.execute("UPDATE players SET update_time=? WHERE tag=?", values)


def in_deck(deck):
    cards = sorted([card["id"] for card in deck])
    print(cards)
    with dbopen(DATABASE) as c:
        sql = """SELECT deck_id FROM decks WHERE (
                 card_1=? AND card_2=? AND card_3=? AND card_4=? AND
                 card_5=? AND card_6=? AND card_7=? AND card_8=?)"""

        if (deck_id := c.execute(sql, cards).fetchone()) is None:
            c.execute(f"INSERT INTO decks values (NULL{', ?' * 8})", cards)            
            return c.lastrowid

        return deck_id


def in_battle(battle, deck_1, deck_2):
    ...


def is_top_ladder(battle):
    ...


def main(player):

    log.info(f"Requesting battles log for {player}")
    url = f"https://api.clashroyale.com/v1/players/%23{player}/battlelog"
    headers = {"Authorization": f"Bearer {API_TOKEN}"}
    battles = requests.get(url, headers=headers).json()

    # TODO handle different resposes

    for battle in battles:
        
        #  TODO if is_top_ladder():
        
        in_player(battle["opponent"][0]["tag"][1:])
        deck_1 = in_deck(battle["team"][0]["cards"])
        deck_2 = in_deck(battle["opponent"][0]["cards"])
        print(deck_2)
        # TODO  in_battle(battle, deck_1, deck_2)

    in_player(player, str(datetime.datetime.now(datetime.timezone.utc)))


if __name__ == "__main__":

    if not DATABASE.exists():
        create_db()
        in_player("G9YV9GR8R")  # root of the search

    # i = 0

    # while player := out_player(0):
    #     main(player)
    #     time.sleep(5)

    #     # just for debug
    #     i += 1
    #     if i > 10:
    #         break

    player = out_player()
    main(player)

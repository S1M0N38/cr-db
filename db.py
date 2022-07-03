import argparse
import datetime as dt
import json
import logging
import os
import pathlib
import sqlite3
import sys
import time
import urllib.request

# Path to this file
here = pathlib.Path(__file__).parent


# CLI arguments
parser = argparse.ArgumentParser()
parser.add_argument("--log", default="INFO", help="Logging level")
args = parser.parse_args()

# Constants
SLEEP = 2  # seconds between api requests
DATABASE = here / "cr.db"


# Token Configuration
API_TOKEN = os.getenv("CLASH_ROYALE_API_TOKEN")
assert API_TOKEN, "undefined API TOKEN"


# Logging setup
log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)

fmt = logging.Formatter(
    fmt="%(levelname)8s - %(asctime)s - %(message)s",
    datefmt="%x %X",
)

fh = logging.FileHandler(here / "db.log")
fh.setFormatter(fmt)
fh.setLevel(logging.DEBUG)

sh = logging.StreamHandler()
sh.setFormatter(fmt)
sh.setLevel(getattr(logging, args.log.upper(), "INFO"))

log.addHandler(fh)
log.addHandler(sh)


# HTTP Configuration
opener = urllib.request.build_opener()
opener.addheaders = [("Authorization", f"Bearer {API_TOKEN}")]


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
                "battle_time TEXT, "
                "tag_1 TEXT, trophies_1 INTEGER, crowns_1 INTEGER, "
                "deck_1 INTEGER, "
                "tag_2 TEXT, trophies_2 INTEGER, crowns_2 INTEGER, "
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

    with dbopen(DATABASE) as c:
        sql = """SELECT deck_id FROM decks WHERE (
                 card_1=? AND card_2=? AND card_3=? AND card_4=? AND
                 card_5=? AND card_6=? AND card_7=? AND card_8=?)"""

        if (deck_id := c.execute(sql, cards).fetchone()) is None:
            c.execute(f"INSERT INTO decks VALUES (NULL{', ?' * 8})", cards)
            return c.lastrowid

        return deck_id[0]


def in_battle(battle, deck_1, deck_2):

    battle_time = dt.datetime.strptime(battle["battleTime"][:-5], "%Y%m%dT%H%M%S")

    sql = """INSERT INTO battles
            (battle_time, 
            tag_1, trophies_1, crowns_1, deck_1, 
            tag_2, trophies_2, crowns_2, deck_2)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    values = [
        str(battle_time),
        battle["team"][0]["tag"][1:],
        battle["team"][0]["startingTrophies"],
        battle["team"][0]["crowns"],
        deck_1,
        battle["opponent"][0]["tag"][1:],
        battle["opponent"][0]["startingTrophies"],
        battle["opponent"][0]["crowns"],
        deck_2,
    ]

    with dbopen(DATABASE) as c:
        c.execute(sql, values)
        return c.lastrowid


def is_top_ladder(battle):

    if (
        battle["gameMode"]["id"] == 72000006
        and battle["opponent"][0]["startingTrophies"] > 6600
        and battle["team"][0]["startingTrophies"] > 6600
    ):
        return True

    return False


def api_request(player):

    log.debug(f"Requesting battles log for {player}")
    url = f"https://api.clashroyale.com/v1/players/%23{player}/battlelog"

    try:
        with opener.open(url) as f:
            return json.loads(f.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        response = json.loads(e.read().decode("utf-8"))
        log.error(f'Reason: {response["reason"]}')
        sys.exit(response["message"])


def main(player):

    battles = api_request(player)
    in_battles = 0

    for battle in battles:

        if is_top_ladder(battle):
            in_player(battle["opponent"][0]["tag"][1:])
            deck_1 = in_deck(battle["team"][0]["cards"])
            deck_2 = in_deck(battle["opponent"][0]["cards"])
            if in_battle(battle, deck_1, deck_2):
                in_battles += 1

    if in_battles > 0:
        log.info(f"Insert [{in_battles}/{len(battles)}] battles for {player}")

    in_player(player, str(dt.datetime.now(dt.timezone.utc)))


if __name__ == "__main__":

    if not DATABASE.exists():
        create_db()
        in_player("G9YV9GR8R")  # root of the search

    while player := out_player(0):
        main(player)
        time.sleep(SLEEP)

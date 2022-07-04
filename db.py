import argparse
import datetime as dt
import http.client
import json
import logging
import os
import pathlib
import sqlite3
import sys
import time


# Just for debugging
def timeme(method):
    def wrapper(*args, **kw):
        startTime = int(round(time.time() * 1000))
        result = method(*args, **kw)
        endTime = int(round(time.time() * 1000))

        print(method.__name__, endTime - startTime, "ms")
        return result

    return wrapper


# CLI arguments
parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
parser.add_argument(
    "--log",
    default="INFO",
    help="console logging level",
)
parser.add_argument(
    "--player",
    default="G9YV9GR8R",
    help="initial player if there is no player in db",
)
parser.add_argument(
    "--db",
    default="cr.db",
    help="database name. Should have '.db' extention",
)
parser.add_argument(
    "--sleep",
    default=5,
    type=float,
    help="sleep time between api requests in seconds",
)
args = parser.parse_args()


# Constants
here = pathlib.Path(__file__).parent
DATABASE = here / args.db


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


# Token Configuration
token_file = here / "token.txt"
if token_file.exists():
    with open("token.txt") as f:
        API_TOKEN = f.read().strip()
    log.info("Using API token from token.txt")
else:
    API_TOKEN = os.getenv("CLASH_ROYALE_API_TOKEN")
    log.info("Using API token from enviroment variable")
assert API_TOKEN, "Undefined API TOKEN"


# HTTP Configuration
headers = {"Authorization": f"Bearer {API_TOKEN}"}
conn = http.client.HTTPSConnection("api.clashroyale.com")


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

        log.info(f"Database succesfully created at\n {DATABASE}")


# @timeme
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


# @timeme
def in_player(player, update_time=None):

    values = [update_time, player]

    with dbopen(DATABASE) as c:
        c.execute("INSERT OR IGNORE INTO players VALUES (?, ?)", values)
        if update_time is not None:
            c.execute("UPDATE players SET update_time=? WHERE tag=?", values)


# @timeme
def in_deck(deck):
    cards = sorted([card["id"] for card in deck])

    with dbopen(DATABASE) as c:
        sql = """SELECT deck_id FROM decks WHERE (
                 card_1=? AND card_2=? AND card_3=? AND card_4=? AND
                 card_5=? AND card_6=? AND card_7=? AND card_8=?)"""

        if (deck_id := c.execute(sql, cards).fetchone()) is None:
            c.execute(f"INSERT INTO decks VALUES (NULL{', ?' * 8})", cards)
            log.debug("Insert new deck into decks")
            return c.lastrowid

        return deck_id[0]


# @timeme
def in_battle(battle, deck_1, deck_2):

    battle_time = dt.datetime.strptime(battle["battleTime"][:-5], "%Y%m%dT%H%M%S")
    tag_1 = battle["team"][0]["tag"][1:]
    tag_2 = battle["opponent"][0]["tag"][1:]

    sql_select = """SELECT battle_id FROM battles WHERE (
                 battle_time=? AND tag_1=? AND tag_2=?)"""

    sql_insert = """INSERT INTO battles
                 (battle_time,
                 tag_1, trophies_1, crowns_1, deck_1,
                 tag_2, trophies_2, crowns_2, deck_2)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""

    values = [
        str(battle_time),
        tag_1,
        battle["team"][0]["startingTrophies"],
        battle["team"][0]["crowns"],
        deck_1,
        tag_2,
        battle["opponent"][0]["startingTrophies"],
        battle["opponent"][0]["crowns"],
        deck_2,
    ]

    with dbopen(DATABASE) as c:

        if c.execute(sql_select, [str(battle_time), tag_1, tag_2]).fetchone():
            return False
        if c.execute(sql_select, [str(battle_time), tag_2, tag_1]).fetchone():
            return False

        c.execute(sql_insert, values)
        return c.lastrowid


def is_top_ladder(battle):

    # TODO add more gameMode id (e.g. LadderGoldRush)

    if (
        battle["gameMode"]["id"] in {72000006, 72000201}
        and battle["opponent"][0]["startingTrophies"] > 6600
        and battle["team"][0]["startingTrophies"] > 6600
    ):
        return True

    return False


@timeme
def api_request(player):

    log.debug(f"Requesting battles log for {player}")
    conn.request("GET", f"/v1/players/#{player}/battlelog", headers=headers)
    response = conn.getresponse()
    data = json.loads(response.read().decode("utf-8"))

    if response.code == 200:
        return data
    else:
        log.error(f'Reason: {data["reason"]}')
        sys.exit(data["message"])


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
        in_player(args.player)  # root of the search

    try:
        while player := out_player():
            main(player)
            time.sleep(args.sleep)
    finally:
        conn.close()
        log.info("Connection with API closed")

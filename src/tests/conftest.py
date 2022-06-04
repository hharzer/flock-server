import os
import json
import pytest

from elasticsearch_dsl import Index, Search
from flock_server import create_api_app, KeybaseHandler, KeybaseNotifications, Setting


class BotStub:
    """
    Stub for pykeybasebot.Bot
    """

    def __init__(self):
        class Chat:
            def __init__(self):
                self.sent_channel = None
                self.sent_message = None

            async def send(self, channel, message):
                self.sent_channel = channel
                self.sent_message = message

        self.chat = Chat()

    def said(self, substring):
        return substring in self.chat.sent_message

    def didnt_say(self, substring):
        return substring not in self.chat.sent_message

    def stayed_silent(self):
        return self.chat.sent_message is None

    @property
    def message(self):
        return self.chat.sent_message


@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    yield create_api_app({"TESTING": True})


@pytest.fixture
def client(app):
    """A test client for the app."""
    client = app.test_client()

    # Delete all users
    Search(index="user").query("match_all").delete()
    Index("user").refresh()

    return client


@pytest.fixture
def handler():
    """The keybase bot's Handler class"""

    # Stub the keybase environment
    os.environ["KEYBASE_USERNAME"] = "flockbot"
    os.environ["KEYBASE_PAPERKEY"] = "put your paper wallet here"
    os.environ["KEYBASE_TEAM"] = "keybase_team_name"
    os.environ["KEYBASE_CHANNEL"] = "flock_notifications_channel"
    os.environ["KEYBASE_ADMIN_USERNAMES"] = "kbusername1,kbusername2"

    return KeybaseHandler()


@pytest.fixture
def bot():
    """Returns a bot stub"""
    return BotStub()


@pytest.fixture
def keybase_notifications():
    """Returns a KeybaseNotifications object"""

    # Delete keybase notification setting
    Search(index="setting").query("match", key="keybase_notifications").delete()
    Index("setting").refresh()

    return KeybaseNotifications()

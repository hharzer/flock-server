import json
import secrets
from datetime import datetime
from functools import wraps
from collections import defaultdict

from flask import Flask, request
from elasticsearch_dsl import Index, Search

from .elasticsearch import es, User
from .keybase_notifications import KeybaseNotifications


def create_api_app(test_config=None):
    keybase_notifications = KeybaseNotifications()

    # Create the flask
    app = Flask(__name__)
    if test_config:
        app.config.update(test_config)

    def check_auth(username, token):
        r = (
            Search(index="user")
            .query("match", username=username)
            .query("match", token=token)
            .execute()
        )
        return len(r) == 1

    def authenticate():
        return {}, 401

    def requires_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                return authenticate()
            return f(*args, **kwargs)

        return decorated

    def api_error(error_msg):
        headers = [
            header
            for header in list(request.headers)
            if header[0].lower() != "authorization"
        ]

        request_body = request.get_data()
        if len(request_body) > 1024:
            request_body = request_body[:1024] + b" [...snip...]"

        error_details = {
            "method": request.method,
            "path": request.path,
            "headers": headers,
            "body": request_body,
            "error_msg": error_msg,
        }

        if auth := request.authorization:
            error_details["username"] = auth.username

        app.logger.debug(f"API error: {error_details}")

        return {"error": True, "error_msg": error_msg}, 400

    def api_success(success_obj=None):
        if not success_obj:
            success_obj = {}
        success_obj["error"] = False
        return success_obj, 200

    def get_name():
        results = (
            Search(index="user")
            .query("match", username=request.authorization["username"])
            .execute()
        )
        if len(results) != 1:
            return None
        user = results[0]
        return user.name

    @app.route("/es-test")
    def es_test():
        r = Search(index="user").query("match", username="user1").execute()
        return str(r.hits)

    @app.route("/register", methods=["POST"])
    def register():
        if not request.json:
            return api_error("Invalid JSON object")
        username = request.json.get("username")
        name = request.json.get("name", "")

        if not username:
            return api_error("You must provide a username")

        # Validate username
        valid_chars = (
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ01234567890_-"
        )
        for c in username:
            if c not in valid_chars:
                return api_error(
                    "Usernames must only contain letters, numbers, '-', or '_'"
                )

        invalid_chars = "`{}!@#$%^&*_"
        new_name = "".join(c for c in name if c not in invalid_chars)
        name = new_name

        # Is the user already registered?
        r = Search(index="user").query("match", username=username).execute()
        if len(r) != 0:
            keybase_notifications.add(
                "user_already_exists", {"username": username, "name": name},
            )

            return api_error(
                f"Your computer ({username}) is already registered with this server"
            )


        # Add user, and force a refresh of the index
        user = User(username=username, name=name, token=secrets.token_hex(16))
        user.save()
        Index("user").refresh()

        keybase_notifications.add(
            "user_registered", {"username": username, "name": name},
        )

        return api_success({"auth_token": user.token})

    @app.route("/ping")
    @requires_auth
    def info():
        # Ping the server, to make sure settings are configured correctly
        return api_success()

    @app.route("/submit", methods=["POST"])
    @requires_auth
    def submit():
        try:
            docs = request.json
        except:
            return api_error("Invalid JSON object")

        if not docs:
            return api_error("Invalid JSON object")

        if type(docs) != list:
            return api_error("Data is not an array")

        # Validate
        for i, doc in enumerate(docs):
            # Item should be an object
            if type(doc) != dict:
                return api_error(f"Item {i} is not an object")

            # hostIdentifier should be the username
            if ("hostIdentifier" not in doc) or (
                request.authorization["username"] != doc["hostIdentifier"]
            ):
                return api_error(f"Item {i} does not contain the correct hostIdentifier")

        # Load the user
        results = (
            Search(index="user")
            .query("match", username=request.authorization["username"])
            .execute()
        )
        user = results[0]

        # Make a list of the types of docs that should trigger notifications
        notification_names = [
            key
            for key in keybase_notifications.notifications
            if keybase_notifications.notifications[key]["type"] == "osquery"
        ]

        # Dictionary that sorts incoming docs by notification type
        docs_by_type = {}

        # Add data to ElasticSearch
        notification_docs = defaultdict(list)
        for doc in docs:
            # Convert 'unixTime' to '@timestamp'
            if "unixTime" in doc:
                doc["@timestamp"] = datetime.utcfromtimestamp(
                    int(doc["unixTime"])
                ).strftime("%Y-%m-%dT%H:%M:%S.000Z")

            # Tag
            doc["username"] = request.authorization["username"]
            doc["user_name"] = user.name

            # Add data
            index = f'flock-{datetime.now().strftime("%Y-%m-%d")}'
            es.index(index=index, doc_type="osquery", body=doc)

        # Figure out what notifications to send
        for doc in docs:
            if "name" in doc and doc["name"] in notification_names:
                notification_docs[doc["name"]].append(doc)

        # Send notifications
        for key, value in notification_docs.items():
            if len(value) == 1:
                keybase_notifications.add(key, value[0])
            elif len(value) > 1:
                added_count = 0
                removed_count = 0
                other_count = 0
                for doc in value:
                    if "action" in doc and doc["action"] == "added":
                        added_count += 1
                    elif "action" in doc and doc["action"] == "removed":
                        removed_count += 1
                    else:
                        other_count += 1
                keybase_notifications.add(
                    key,
                    {
                        "type": "summary",
                        "username": request.authorization["username"],
                        "name": user.name,
                        "added_count": added_count,
                        "removed_count": removed_count,
                        "other_count": other_count,
                    },
                )

        return api_success({"processed_count": len(docs)})

    @app.route("/submit_flock_logs", methods=["POST"])
    @requires_auth
    def submit_flock_logs():
        # Validate that the data is JSON
        try:
            docs = request.json
        except:
            return api_error("Invalid JSON object")

        if type(docs) != list:
            return api_error("Data is not an array")

        # Validate
        for i, doc in enumerate(docs):
            # Item should be an object
            if type(doc) != dict:
                return api_error(f"Item {i} is not an object")

            # Item should have type and timestamp, and maybe twig_id
            if "type" not in doc:
                return api_error(f"Item {i} does not contain a type field")
            if "timestamp" not in doc:
                return api_error(f"Item {i} does not contain a timestamp field")
            if (
                doc["type"] in ["enable_twig", "disable_twig"]
                and "twig_id" not in doc
            ):
                return api_error(
                    f"Item {i} is about a twig, but does not contain a twig_id field"
                )


        # Add keybase notifications
        for doc in docs:
            if doc["type"] in [
                "server_enabled",
                "server_disabled",
                "twigs_enabled",
                "twigs_disabled",
            ]:
                details = {
                    "username": request.authorization["username"],
                    "name": get_name(),
                }
                if doc["type"] in ["twigs_enabled", "twigs_disabled"]:
                    details["twig_ids"] = doc["twig_ids"]
                keybase_notifications.add(doc["type"], details)

        return api_success({"processed_count": len(docs)})

    return app

import os
import json
import secrets
from functools import wraps
from flask import Flask, request, Response


class Tokens(object):
    def __init__(self):
        self.path = '/data/tokens.json'
        self.load()

    def load(self):
        if not os.path.exists(self.path):
            self.tokens = {}
            self.save()
        else:
            with open(self.path) as f:
                self.tokens = json.load(f)

    def save(self):
        with open(self.path, 'w') as f:
            json.dump(self.tokens, f)

    def get(self, username):
        if self.exists(username):
            return self.tokens[username]
        else:
            return None

    def exists(self, username):
        return username in self.tokens

    def generate(self, username):
        token = secrets.token_hex(16)
        self.tokens[username] = token
        self.save()
        return token


tokens = Tokens()
app = Flask(__name__)


def check_auth(username, password):
    return tokens.exists(username) and password == tokens.get(username)


def authenticate():
    return Response(status=401, mimetype="application/json")


def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def api_error(error_msg):
    return Response(json.dumps({
        "error": True,
        "error_msg": error_msg
    }), status=400, mimetype="application/json")


def api_success(success_obj):
    success_obj["error"] = False
    return Response(json.dumps(success_obj), status=200, mimetype="application/json")


@app.route("/")
def index():
    return "<html><head><title>Flock gateway</title></head><body><p style='font-size: 20em; text-align: center;'>🦉</p></body></html>"


@app.route("/register", methods=["POST"])
def register():
    username = request.form.get('username')

    if not username:
        return api_error("You must provide a username")

    if tokens.exists(username):
        return api_error("That username is already registered")

    token = tokens.generate(username)
    return api_success( {"auth_token": token })


@app.route("/submit", methods=["POST"])
@requires_auth
def submit():
    return api_error("Not implemented yet")


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0')

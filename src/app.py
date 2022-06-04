import time
import requests
import os

from flock_server import (
    User,
    Setting,
    KeybaseNotification,
    create_api_app,
    start_keybase_bot,
    elasticsearch_url,
)


if __name__ == "__main__":
    # Wait for ElasticSearch to start
    print("Waiting for ElasticSearch")
    while True:
        try:
            if "ELASTIC_CA_CERT" in os.environ:
                ca_cert_path = os.environ["ELASTIC_CA_CERT"]
            else:
                ca_cert_path = None

            r = requests.get(elasticsearch_url, verify=ca_cert_path)
            print(f"{elasticsearch_url} is ready")
            break

        except:
            print(f"{elasticsearch_url} not ready, waiting ...")
            time.sleep(5)

    # Initialize models
    print("Initializing user model")
    try:
        User.init()
    except:
        pass
    try:
        Setting.init()
    except:
        pass
    try:
        KeybaseNotification.init()
    except:
        pass

    if os.environ.get("FLOCK_KEYBASE") == "1":
        # Start keybase bot
        start_keybase_bot()

    else:
        # Start web service
        app = create_api_app()
        app.run(host="0.0.0.0", port=5000, debug=True)

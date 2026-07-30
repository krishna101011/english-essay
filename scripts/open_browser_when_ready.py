"""Open the default browser to the local dev server once it actually answers.

Used by start.bat: it launches this in the background right before starting
uvicorn in the foreground, so the browser opens itself as soon as the server
is ready instead of after a blind fixed delay (which is flaky on a slower
machine or a cold --reload).
"""

import time
import urllib.error
import urllib.request
import webbrowser

URL = "http://localhost:8000"
TIMEOUT_SECONDS = 30
POLL_INTERVAL_SECONDS = 0.25


def _server_is_ready() -> bool:
    try:
        urllib.request.urlopen(URL, timeout=0.5)
        return True
    except urllib.error.HTTPError:
        # Any HTTP response - even a redirect to /login - means uvicorn is
        # up and answering requests.
        return True
    except OSError:
        return False


def main() -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _server_is_ready():
            webbrowser.open(URL)
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    # Server never came up within the timeout - nothing to open.


if __name__ == "__main__":
    main()

"""Check the source of UI writes for browser and WeChat clients."""

from flask import request
from werkzeug.exceptions import Forbidden


def check_origin(message='请从战术室页面发起操作'):
    origin = request.headers.get('Origin')
    if not origin or origin.rstrip('/') == request.host_url.rstrip('/'):
        return

    # A reverse proxy can change the scheme and host seen by Flask. Fetch
    # Metadata reports the origin relationship as seen by the browser.
    if origin.startswith(('http://', 'https://')) and request.headers.get('Sec-Fetch-Site') == 'same-origin':
        return

    # WeChat clients may include an app-specific page path in the header.
    if origin == 'https://servicewechat.com' or origin.startswith('https://servicewechat.com/'):
        return

    raise Forbidden(message)

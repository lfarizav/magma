"""
Copyright (c) 2018-present, Facebook, Inc.
All rights reserved.

This source code is licensed under the BSD-style license found in the
LICENSE file in the root directory of this source tree. An additional grant
of patent rights can be found in the PATENTS file in the same directory.
"""

import logging
from collections import namedtuple

from magma.redirectd.redirect_store import RedirectDict

import wsgiserver
from flask import Flask, redirect, request, render_template

""" Use 404 when subscriber not found, 302 for 'Found' redirect """
HTTP_NOT_FOUND = 404
HTTP_REDIRECT = 302

NOT_FOUND_HTML = '404.html'

RedirectInfo = namedtuple('RedirectInfo', ['subscriber_ip', 'server_response'])
ServerResponse = namedtuple(
    'ServerResponse', ['redirect_address', 'http_code']
)


def flask_redirect(**kwargs):
    """ Check redis for src_ip, redirect if found and send 404 if not """
    response = kwargs['get_redirect_response'](request.remote_addr)
    redirect_info = RedirectInfo(request.remote_addr, response)

    scribe_client = kwargs['scribe_client']
    if scribe_client is not None:
        scribe_client.log_to_scribe(redirect_info)

    logging.info(
        "Request from {}: sent http code {} - redirected to {}".format(
            redirect_info.subscriber_ip, response.http_code,
            response.redirect_address
        )
    )

    if response.http_code is HTTP_NOT_FOUND:
        return render_template(
            response.redirect_address,
            subscriber={'ip': redirect_info.subscriber_ip}
        ), HTTP_NOT_FOUND

    return redirect(response.redirect_address, code=response.http_code)


def setup_flask_server(scribe_client):
    app = Flask(__name__)
    url_dict = RedirectDict()

    def get_redirect_response(src_ip):
        """
        If addr type is IPv4/IPv6 prepend http, if url don't change
        TODO: not sure what to do with SIP_URI
        """
        if src_ip not in url_dict:
            return ServerResponse(NOT_FOUND_HTML, HTTP_NOT_FOUND)

        redirect_addr = url_dict[src_ip].server_address
        if url_dict[src_ip].address_type == url_dict[src_ip].IPv4:
            redirect_addr = 'http://' + redirect_addr + '/'
        elif url_dict[src_ip].address_type == url_dict[src_ip].IPv6:
            redirect_addr = 'http://[' + redirect_addr + ']/'

        return ServerResponse(redirect_addr, HTTP_REDIRECT)

    app.add_url_rule(
        '/', 'index', flask_redirect,
        defaults={'get_redirect_response': get_redirect_response,
                  'scribe_client': scribe_client}
    )
    app.add_url_rule(
        '/<path:path>', 'index', flask_redirect,
        defaults={'get_redirect_response': get_redirect_response,
                  'scribe_client': scribe_client}
    )
    return app


def run_flask(ip, port, scribe_logger, exit_callback):
    """
    Runs the flask server, this is a daemon, so it exits when redirectd exits
    """

    app = setup_flask_server(scribe_logger)

    server = wsgiserver.WSGIServer(app, host=ip, port=port)
    try:
        server.start()
    finally:
        # When the flask server finishes running, do any other cleanup
        exit_callback()
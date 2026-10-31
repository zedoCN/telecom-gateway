"""Bounded, redirect-free standard-library client for the supported LuCI CGI."""

import http.client
import http.cookies
import ipaddress
import json
import math
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import models
from .models import GatewayError

MAX_RESPONSE_BYTES = 8 << 20
_TOKEN_PATTERNS = (
    re.compile(rb"token[^a-z0-9]+([a-z0-9]{32})(?![a-z0-9])", re.I),
    re.compile(rb"\b([a-z0-9]{32})\b", re.I),
)


def _reject_json_constant(_):
    raise ValueError()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _RequestDeadline:
    """Interrupt socket I/O even when a peer continuously drips response bytes."""

    def __init__(self, deadline):
        self.deadline = deadline
        self.connection = None
        self.socket = None
        self.expired = threading.Event()
        self.timer = threading.Timer(max(0, deadline - time.monotonic()), self._expire)
        self.timer.daemon = True

    def _expire(self):
        self.expired.set()
        connection = self.connection
        active_socket = self.socket or (connection.sock if connection is not None else None)
        if active_socket is not None:
            try:
                active_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    def check(self):
        if self.expired.is_set() or time.monotonic() >= self.deadline:
            self._expire()
            raise TimeoutError()


class _DeadlineHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, controller, **kwargs):
        self._controller = controller
        super().__init__(*args, **kwargs)
        controller.connection = self

    def connect(self):
        super().connect()
        self._controller.socket = self.sock
        self._controller.check()


class _DeadlineHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, controller, **kwargs):
        self._controller = controller
        super().__init__(*args, **kwargs)
        controller.connection = self

    def connect(self):
        super().connect()
        self._controller.socket = self.sock
        self._controller.check()


class _HTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def http_open(self, req):
        return self.do_open(lambda *a, **kw: _DeadlineHTTPConnection(
            *a, controller=self._controller, **kw), req)


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller

    def https_open(self, req):
        return self.do_open(lambda *a, **kw: _DeadlineHTTPSConnection(
            *a, controller=self._controller, **kw), req,
            context=self._context)


class GatewayClient:
    def __init__(self, base_url="http://192.168.1.1", username="", password="",
                 timeout=15.0, deadline=None):
        if not isinstance(base_url, str):
            raise GatewayError("gateway URL is invalid")
        base_url = base_url.strip() or "http://192.168.1.1"
        try:
            if any(ord(char) <= 32 or ord(char) == 127 for char in base_url):
                raise ValueError()
            parsed = urllib.parse.urlsplit(base_url)
            if (parsed.scheme not in ("http", "https") or not parsed.hostname
                    or parsed.username is not None or parsed.password is not None
                    or "?" in base_url or "#" in base_url or parsed.netloc.endswith(":")):
                raise ValueError()
            if parsed.port is not None and not 1 <= parsed.port <= 65535:
                raise ValueError()
            host = parsed.hostname
            if ":" in host:
                ipaddress.IPv6Address(host)
                host = "[" + host + "]"
            else:
                host = host.encode("idna").decode("ascii")
                if len(host) > 254 or any(not re.fullmatch(
                        r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                        for label in host.rstrip(".").split(".")):
                    raise ValueError()
            authority = host + (f":{parsed.port}" if parsed.port is not None else "")
        except (ValueError, UnicodeError):
            raise GatewayError("gateway URL must be http(s) with a valid host and no credentials, query, or fragment") from None
        if (type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0
                or (deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)))):
            raise GatewayError("gateway timeout and deadline must be finite positive timeout values")
        if not isinstance(username, str) or not isinstance(password, str):
            raise GatewayError("gateway username and password must be strings")
        self._base_url = urllib.parse.urlunsplit((parsed.scheme, authority, "", "", ""))
        self._username = username
        self._password = password
        self._timeout = timeout
        self._deadline = deadline
        self._cookie = None
        self._token = None

    def login(self):
        self._cookie = self._token = None
        if not self._username or not self._password:
            raise GatewayError("gateway username and password are required")
        try:
            _, headers, _ = self._request("POST", "/cgi-bin/luci",
                {"username": self._username, "psd": self._password}, authenticated=False,
                expected_status=302, read_body=False)
            cookies = http.cookies.SimpleCookie()
            for header in headers.get_all("Set-Cookie", []):
                cookies.load(header)
            cookie = cookies.get("sysauth")
            if cookie is None or not cookie.value or any(ord(c) < 32 or ord(c) == 127 for c in cookie.value):
                raise GatewayError("gateway login response did not include a valid sysauth cookie")
            self._cookie = "sysauth=" + cookie.coded_value
            body = self._request("GET", "/cgi-bin/luci")[2]
            for pattern in _TOKEN_PATTERNS:
                match = pattern.search(body)
                if match:
                    self._token = match[1].decode("ascii")
                    return
            raise GatewayError("gateway page did not contain a 32-character session token")
        except http.cookies.CookieError:
            self._cookie = self._token = None
            raise GatewayError("gateway login response contained an invalid cookie") from None
        except GatewayError:
            self._cookie = self._token = None
            raise

    def logout(self):
        try:
            self._post("/cgi-bin/luci/admin/logout")
        finally:
            self._cookie = self._token = None

    def status(self):
        return models.status(self._get_json("/cgi-bin/luci/admin/settings/gwstatus"))

    def info(self):
        return models.info(self._get_json("/cgi-bin/luci/admin/settings/gwinfo?get=all"))

    def devices(self):
        return models.devices(self._get_json("/cgi-bin/luci/admin/allInfo"))

    def port_mappings(self):
        return models.port_mappings(self._get_json("/cgi-bin/luci/admin/settings/pmDisplay"))

    def add_port_mapping(self, mapping):
        if not isinstance(mapping, dict):
            raise GatewayError("port mapping must be an object")
        name, client = mapping.get("desp", ""), mapping.get("client", "")
        protocol = mapping.get("protocol", "")
        if not isinstance(name, str) or not name.strip() or not isinstance(client, str) or not client.strip():
            raise GatewayError("port mapping name and client IP are required")
        if not isinstance(protocol, str) or protocol.upper() not in ("TCP", "UDP", "BOTH"):
            raise GatewayError("port mapping protocol must be TCP, UDP, or BOTH")
        for key in ("exPort", "inPort"):
            if type(mapping.get(key)) is not int or not 1 <= mapping[key] <= 65535:
                raise GatewayError("port mapping ports must be between 1 and 65535")
        self._post("/cgi-bin/luci/admin/settings/pmSetSingle", {
            "op": "add", "srvname": name, "client": client, "protocol": protocol.upper(),
            "exPort": mapping["exPort"], "inPort": mapping["inPort"]})

    def enable_port_mapping(self, name):
        self._port_action("enable", name)

    def disable_port_mapping(self, name):
        self._port_action("disable", name)

    def delete_port_mapping(self, name):
        self._port_action("del", name)

    def reboot(self):
        self._post("/cgi-bin/luci/admin/reboot")

    def _port_action(self, action, name):
        if not isinstance(name, str) or not name.strip():
            raise GatewayError("port mapping name is required")
        self._post("/cgi-bin/luci/admin/settings/pmSetSingle", {"op": action, "srvname": name})

    def _post(self, path, values=None):
        if not self._cookie or not self._token:
            raise GatewayError("gateway client is not authenticated")
        values = dict(values or {}, token=self._token)
        try:
            self._request("POST", path, values)
        except GatewayError:
            raise GatewayError("gateway write result is uncertain; read back the affected object before retrying") from None

    def _get_json(self, path):
        body = self._request("GET", path)[2]
        try:
            value = json.loads(body, parse_constant=_reject_json_constant)
        except (ValueError, UnicodeError, RecursionError):
            raise GatewayError("gateway response was not valid JSON") from None
        if not isinstance(value, dict):
            raise GatewayError("gateway response must be a JSON object")
        return value

    def _request(self, method, path, values=None, authenticated=True,
                 expected_status=200, read_body=True):
        if authenticated and not self._cookie:
            raise GatewayError("gateway client is not authenticated")
        end = time.monotonic() + self._timeout
        if self._deadline is not None:
            end = min(end, self._deadline)
        controller = _RequestDeadline(end)
        response = None
        try:
            controller.check()
            headers = {}
            if authenticated:
                headers["Cookie"] = self._cookie
            data = None
            if method == "POST":
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                data = urllib.parse.urlencode(values or {}).encode("ascii")
            request = urllib.request.Request(self._base_url + path, data=data, headers=headers, method=method)
            opener = urllib.request.build_opener(_NoRedirect(), _HTTPHandler(controller), _HTTPSHandler(controller))
            controller.timer.start()
            try:
                response = opener.open(request, timeout=max(0.001, end - time.monotonic()))
            except urllib.error.HTTPError as error:
                response = error
            controller.check()
            if response.status != expected_status:
                raise GatewayError(f"gateway returned unexpected HTTP status {response.status}")
            body = response.read(MAX_RESPONSE_BYTES + 1) if read_body else b""
            controller.check()
            if len(body) > MAX_RESPONSE_BYTES:
                raise GatewayError("gateway response exceeded the 8 MiB limit")
            content_length = response.headers.get("Content-Length")
            if read_body and content_length is not None and int(content_length) != len(body):
                raise GatewayError("gateway response was incomplete")
            return response.status, response.headers, body
        except GatewayError:
            raise
        except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
            raise GatewayError("gateway request failed or timed out") from None
        finally:
            controller.timer.cancel()
            if response is not None:
                response.close()

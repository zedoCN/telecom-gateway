"""Synthetic HTTP integration tests; no real gateway or credential store."""

import contextlib
import json
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs

from ctgw.client import GatewayClient, GatewayError, MAX_RESPONSE_BYTES


TOKEN = "0" * 32
SESSION = "synthetic-session"
LOGIN = "/cgi-bin/luci"
STATUS = LOGIN + "/admin/settings/gwstatus"
INFO = LOGIN + "/admin/settings/gwinfo?get=all"
DEVICES = LOGIN + "/admin/allInfo"
MAPPINGS = LOGIN + "/admin/settings/pmDisplay"
WRITE = LOGIN + "/admin/settings/pmSetSingle"
REBOOT = LOGIN + "/admin/reboot"
LOGOUT = LOGIN + "/admin/logout"


@contextlib.contextmanager
def gateway():
    state = {"requests": [], "routes": {}}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.handle_request()

        def do_POST(self):
            self.handle_request()

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            form = parse_qs(body.decode("ascii"), keep_blank_values=True)
            state["requests"].append({
                "method": self.command, "path": self.path, "form": form,
                "cookie": self.headers.get("Cookie"),
                "content_type": self.headers.get("Content-Type"),
            })
            route = state["routes"].get((self.command, self.path))
            try:
                if callable(route):
                    route(self)
                    return
                if route is not None:
                    status, headers, content = route
                elif self.path == LOGIN and self.command == "POST":
                    status, headers, content = 302, {"Set-Cookie": f"sysauth={SESSION}; Path=/"}, b""
                elif self.path == LOGIN:
                    status, headers, content = 200, {}, f'<script>var token = "{TOKEN}";</script>'.encode()
                else:
                    status, headers, content = 200, {}, b"{}"
                if isinstance(content, dict) or isinstance(content, list):
                    content = json.dumps(content).encode()
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class ClientTests(unittest.TestCase):
    def make_client(self, state, **kwargs):
        return GatewayClient(state["url"], "synthetic-user", "synthetic-password", **kwargs)

    def test_login_cookie_and_token_forms(self):
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            client.status()
            client.add_port_mapping({"desp": "example-game", "client": "192.0.2.10",
                                     "protocol": "udp", "exPort": 8211, "inPort": 8212})
            client.enable_port_mapping("example-game")
            client.disable_port_mapping("example-game")
            client.delete_port_mapping("example-game")
            client.reboot()
            client.logout()
            requests = state["requests"]
            self.assertEqual(requests[0]["form"], {"username": ["synthetic-user"], "psd": ["synthetic-password"]})
            self.assertIsNone(requests[0]["cookie"])
            for request in requests[1:]:
                self.assertEqual(request["cookie"], f"sysauth={SESSION}")
            self.assertEqual(requests[3]["form"], {
                "op": ["add"], "srvname": ["example-game"], "client": ["192.0.2.10"],
                "protocol": ["UDP"], "exPort": ["8211"], "inPort": ["8212"], "token": [TOKEN]})
            self.assertEqual([r["form"].get("op") for r in requests[4:7]], [["enable"], ["disable"], ["del"]])
            for request in requests[3:]:
                self.assertEqual(request["form"]["token"], [TOKEN])
                self.assertEqual(request["content_type"], "application/x-www-form-urlencoded")
            self.assertEqual([r["path"] for r in requests[-2:]], [REBOOT, LOGOUT])
            with self.assertRaisesRegex(GatewayError, "not authenticated"):
                client.status()

    def test_login_failures_clear_session(self):
        cases = [
            ((200, {}, b"secret-password-response"), None),
            ((302, {}, b""), None),
            ((302, {"Set-Cookie": "sysauth="}, b""), None),
            (None, (200, {}, b"no token here")),
            (None, (302, {"Location": "/secret-destination"}, b"")),
        ]
        for post_response, get_response in cases:
            with self.subTest(post=post_response, get=get_response), gateway() as state:
                client = self.make_client(state)
                client.login()
                if post_response:
                    state["routes"][("POST", LOGIN)] = post_response
                if get_response:
                    state["routes"][("GET", LOGIN)] = get_response
                with self.assertRaises(GatewayError) as error:
                    client.login()
                self.assertNotIn("secret", str(error.exception))
                count = len(state["requests"])
                with self.assertRaisesRegex(GatewayError, "not authenticated"):
                    client.reboot()
                self.assertEqual(count, len(state["requests"]))

    def test_rejects_missing_credentials_without_network(self):
        with gateway() as state:
            client = GatewayClient(state["url"])
            with self.assertRaises(GatewayError):
                client.login()
            self.assertEqual(state["requests"], [])

    def test_get_and_post_redirects_never_follow(self):
        with gateway() as destination, gateway() as state:
            client = self.make_client(state)
            client.login()
            location = destination["url"] + "/private-location?token=secret-token"
            for code in (301, 302, 303, 307, 308):
                for method, path, action in (("GET", STATUS, client.status), ("POST", REBOOT, client.reboot)):
                    state["routes"][(method, path)] = (code, {"Location": location}, b"private-body")
                    before = len(state["requests"])
                    with self.subTest(code=code, method=method), self.assertRaises(GatewayError) as error:
                        action()
                    self.assertEqual(len(state["requests"]), before + 1)
                    self.assertNotIn("private", str(error.exception))
                    self.assertNotIn("secret-token", str(error.exception))
            self.assertEqual(destination["requests"], [])

    def test_login_redirect_location_not_followed(self):
        with gateway() as state:
            state["routes"][("POST", LOGIN)] = (302, {
                "Set-Cookie": f"sysauth={SESSION}", "Location": "/do-not-follow"}, b"")
            client = self.make_client(state)
            client.login()
            self.assertEqual([r["path"] for r in state["requests"]], [LOGIN, LOGIN])

    def test_status_defaults_and_info_whitelist(self):
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            state["routes"][("GET", STATUS)] = (200, {}, {"cpuUsed": 12, "sysTime": 34, "unknown": "hidden"})
            self.assertEqual(client.status(), {"cpuUsed": 12, "scount": 0, "sysTime": 34,
                "upTime": 0, "wcount": 0, "wlcount": 0, "itv": False, "voip": False})
            state["routes"][("GET", INFO)] = (200, {}, {"Vendor": "example", "DevType": "",
                "LANIP": None, "wifiOnOff": True, "privatePassword": "never-return"})
            self.assertEqual(client.info(), {"wifiOnOff": True, "Vendor": "example"})

    def test_device_and_port_mapping_normalization(self):
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            state["routes"][("GET", DEVICES)] = (200, {}, {
                "wcount": 2, "wlcount": 1, "pc1": {"ip": "192.0.2.10", "devName": "wired", "private": "hidden"},
                "wifi1": {"devName": "wireless"}, "pc3": {"devName": "outside-count"}})
            devices = client.devices()
            self.assertEqual(devices["pc"], [{"ip": "192.0.2.10", "devName": "wired", "upSpeed": 0,
                                             "onlineTime": 0, "downSpeed": 0}])
            self.assertEqual(devices["wifi"][0]["devName"], "wireless")
            self.assertEqual(devices["wcount"], 2)
            self.assertNotIn("pc1", devices)
            state["routes"][("GET", MAPPINGS)] = (200, {}, {"count": 2,
                "lanIp": "192.0.2.1", "pmRule1": {"desp": "example", "exPort": 22}})
            self.assertEqual(client.port_mappings(), {"count": 2, "lanIp": "192.0.2.1", "pmRule": [
                {"desp": "example", "exPort": 22, "enable": 0, "inPort": 0, "client": "", "protocol": ""}]})
            state["routes"][("GET", DEVICES)] = (200, {}, {})
            self.assertNotIn("pc", client.devices())
            self.assertNotIn("wifi", client.devices())
            state["routes"][("GET", MAPPINGS)] = (200, {}, {})
            self.assertEqual(client.port_mappings(), {"count": 0})

    def test_rejects_invalid_json_types_and_counts(self):
        cases = [(STATUS, b"null", "status"), (STATUS, [], "status"),
                 (STATUS, b"{invalid secret-body", "status"),
                 (STATUS, {"cpuUsed": True}, "status"), (STATUS, {"sysTime": 1 << 70}, "status"),
                 (STATUS, {"cpuUsed": 1.5}, "status"), (STATUS, {"itv": 1}, "status"),
                 (INFO, {"Vendor": 1}, "info"), (STATUS, b'{"cpuUsed":NaN}', "status"),
                 (DEVICES, {"wcount": -1}, "devices"), (DEVICES, {"wlcount": 4097}, "devices"),
                 (DEVICES, {"wcount": "1"}, "devices"),
                 (DEVICES, {"wcount": 1, "pc1": []}, "devices"),
                 (MAPPINGS, {"count": 4097}, "port_mappings"),
                 (MAPPINGS, {"count": 1, "pmRule1": None}, "port_mappings")]
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            for path, body, method in cases:
                with self.subTest(method=method, body=body):
                    state["routes"][("GET", path)] = (200, {}, body)
                    with self.assertRaises(GatewayError) as error:
                        getattr(client, method)()
                    self.assertNotIn("secret-body", str(error.exception))

    def test_response_size_limit_and_exact_boundary(self):
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            state["routes"][("GET", STATUS)] = (200, {}, b"{}" + b" " * (MAX_RESPONSE_BYTES - 2))
            self.assertEqual(client.status()["cpuUsed"], 0)
            state["routes"][("GET", STATUS)] = (200, {}, b" " * (MAX_RESPONSE_BYTES + 1))
            with self.assertRaisesRegex(GatewayError, "8 MiB"):
                client.status()
            state["routes"][("POST", REBOOT)] = (200, {}, b" " * (MAX_RESPONSE_BYTES + 1))
            with self.assertRaisesRegex(GatewayError, "uncertain.*read back"):
                client.reboot()

    def test_unauthenticated_methods_send_no_requests(self):
        with gateway() as state:
            client = self.make_client(state)
            actions = [client.status, client.info, client.devices, client.port_mappings, client.logout,
                       client.reboot, lambda: client.enable_port_mapping("example"),
                       lambda: client.disable_port_mapping("example"), lambda: client.delete_port_mapping("example"),
                       lambda: client.add_port_mapping({"desp": "example", "client": "192.0.2.10",
                           "protocol": "TCP", "exPort": 22, "inPort": 22})]
            for action in actions:
                with self.assertRaisesRegex(GatewayError, "not authenticated"):
                    action()
            self.assertEqual(state["requests"], [])

    def test_invalid_mapping_rejected_without_post(self):
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            valid = {"desp": "example", "client": "192.0.2.10", "protocol": "TCP", "exPort": 22, "inPort": 22}
            for patch_value in ({"desp": " "}, {"client": ""}, {"protocol": "ICMP"}, {"exPort": 0},
                                {"inPort": 65536}, {"exPort": True}, {"inPort": "22"}):
                with self.assertRaises(GatewayError):
                    client.add_port_mapping(dict(valid, **patch_value))
            self.assertEqual(len(state["requests"]), 2)

    def test_write_disconnect_is_uncertain_and_never_retried(self):
        def disconnect(handler):
            handler.connection.shutdown(socket.SHUT_RDWR)
            handler.connection.close()
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            state["routes"][("POST", REBOOT)] = disconnect
            with self.assertRaisesRegex(GatewayError, "uncertain.*read back"):
                client.reboot()
            self.assertEqual(len([r for r in state["requests"] if r["path"] == REBOOT]), 1)

    def test_incomplete_write_response_is_uncertain(self):
        def truncated(handler):
            handler.send_response(200)
            handler.send_header("Content-Length", "100")
            handler.end_headers()
            handler.wfile.write(b"{}")
        with gateway() as state:
            client = self.make_client(state)
            client.login()
            state["routes"][("POST", REBOOT)] = truncated
            with self.assertRaisesRegex(GatewayError, "uncertain"):
                client.reboot()
            self.assertEqual(len(state["requests"]), 3)

    def test_timeout_bounds_slow_headers_and_slow_bodies(self):
        def slow_headers(handler):
            for byte in b"HTTP/1.0 200 OK\r\nContent-Length: 2\r\n\r\n{}":
                handler.wfile.write(bytes([byte]))
                handler.wfile.flush()
                time.sleep(0.02)

        def slow_body(handler):
            handler.send_response(200)
            handler.send_header("Content-Length", "100")
            handler.end_headers()
            for _ in range(100):
                handler.wfile.write(b" ")
                handler.wfile.flush()
                time.sleep(0.02)

        for slow in (slow_headers, slow_body):
            with self.subTest(slow=slow.__name__), gateway() as state:
                client = self.make_client(state, timeout=0.12)
                client.login()
                state["routes"][("GET", STATUS)] = slow
                started = time.monotonic()
                with self.assertRaises(GatewayError):
                    client.status()
                self.assertLess(time.monotonic() - started, 0.8)
                state["routes"][("POST", REBOOT)] = slow
                with self.assertRaisesRegex(GatewayError, "uncertain"):
                    client.reboot()
                self.assertEqual(len([r for r in state["requests"] if r["path"] == REBOOT]), 1)

    def test_total_deadline_prevents_subsequent_request(self):
        with gateway() as state:
            client = self.make_client(state, deadline=time.monotonic() + 0.2)
            client.login()
            time.sleep(0.22)
            with self.assertRaises(GatewayError):
                client.status()
            self.assertEqual(len(state["requests"]), 2)

    def test_invalid_url_and_timeouts_do_not_echo_sensitive_input(self):
        for url in ("file:///private/secret", "http:///secret", "http://user:secret@example.invalid",
                    "http://example.invalid?secret", "http://example.invalid#secret", "http://host:secret",
                    "http://host:99999", "http://host:", "http://ho\nst", "http://[invalid]",
                    "http://..", "http://-invalid.example", "http://a..example"):
            with self.subTest(url=url), self.assertRaises(GatewayError) as error:
                GatewayClient(url)
            self.assertNotIn("secret", str(error.exception))
        for timeout in (0, -1, float("inf"), float("nan"), True, "15"):
            with self.assertRaises(GatewayError):
                GatewayClient(timeout=timeout)

    def test_environment_proxy_is_honored(self):
        with gateway() as state:
            # A local synthetic HTTP proxy sees the absolute request URI; no external connection occurs.
            proxy_url = state["url"]
            target = "http://gateway.example.invalid"
            state["routes"][("POST", target + LOGIN)] = (302, {"Set-Cookie": f"sysauth={SESSION}"}, b"")
            state["routes"][("GET", target + LOGIN)] = (200, {}, ("token='" + TOKEN + "'").encode())
            state["routes"][("GET", target + STATUS)] = (200, {}, {"cpuUsed": 7})
            environment = {"http_proxy": proxy_url, "https_proxy": proxy_url,
                           "no_proxy": "", "HTTP_PROXY": proxy_url, "HTTPS_PROXY": proxy_url, "NO_PROXY": ""}
            with patch.dict("os.environ", environment):
                client = GatewayClient(target, "synthetic-user", "synthetic-password")
                client.login()
                self.assertEqual(client.status()["cpuUsed"], 7)
            self.assertEqual(len(state["requests"]), 3)


if __name__ == "__main__":
    unittest.main()

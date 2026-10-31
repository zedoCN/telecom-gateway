"""CLI semantics, credential selection, redaction and verified exact changes."""

import argparse
from collections import Counter
import contextlib
import importlib.metadata
import ipaddress
import json
import math
import os
import platform
import re
import sys
import time

from . import __version__
from .client import GatewayClient, GatewayError
from .credentials import CredentialError, Profile, Store


class UsageError(Exception):
    pass


class _ParserExit(Exception):
    def __init__(self, status):
        self.status = status


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's generated message can repeat arbitrary user-supplied values.
        raise UsageError("invalid arguments; run ctgw help")

    def exit(self, status=0, message=None):
        raise _ParserExit(status)


def duration(value):
    units = {"ns": 1e-9, "us": 1e-6, "µs": 1e-6, "μs": 1e-6,
             "ms": .001, "s": 1, "m": 60, "h": 3600}
    if re.fullmatch(r"\d+(?:\.\d*)?|\.\d+", value):
        result = float(value)
    else:
        chunks = re.findall(r"(\d+(?:\.\d*)?|\.\d+)(ns|us|µs|μs|ms|s|m|h)", value)
        if not chunks or "".join(n + u for n, u in chunks) != value:
            raise UsageError("timeout must be a positive duration, for example 15s")
        result = sum(float(n) * units[u] for n, u in chunks)
    if not math.isfinite(result) or result <= 0:
        raise UsageError("timeout must be a positive duration")
    return result


def parser():
    root = Parser(prog="ctgw", description="Manage supported China Telecom gateways.",
                  epilog="Global flags precede commands. Every gateway change requires --yes.")
    root.add_argument("--url", help="gateway URL (profile, CTGW_URL, or http://192.168.1.1)")
    root.add_argument("--username", help="gateway username (profile or CTGW_USERNAME)")
    root.add_argument("--password-stdin", action="store_true", help="read password from stdin")
    root.add_argument("--json", action="store_true", help="structured output; info remains redacted")
    root.add_argument("--timeout", type=duration, default=15.0, help="total request budget (default 15s)")
    commands = root.add_subparsers(dest="command")
    for command in ("help", "version", "doctor", "status", "devices"):
        commands.add_parser(command)
    info = commands.add_parser("info")
    info.add_argument("--show-sensitive", action="store_true")
    auth = commands.add_parser("auth").add_subparsers(dest="auth_action", required=True)
    for action in ("login", "status", "logout"):
        auth.add_parser(action)
    reboot = commands.add_parser("reboot")
    reboot.add_argument("--yes", action="store_true")
    ports = commands.add_parser("port").add_subparsers(dest="port_action", required=True)
    ports.add_parser("list")
    for action in ("add", "enable", "disable", "delete"):
        item = ports.add_parser(action)
        item.add_argument("--name", required=True)
        item.add_argument("--yes", action="store_true")
        if action == "add":
            item.add_argument("--client", required=True)
            item.add_argument("--protocol", type=str.upper, choices=("TCP", "UDP", "BOTH"), required=True)
            item.add_argument("--external-port", type=int, required=True)
            item.add_argument("--internal-port", type=int, required=True)
    return root


def _validate_action(options):
    if options.command == "reboot" and not options.yes:
        raise UsageError("reboot requires --yes")
    if options.command != "port" or options.port_action == "list":
        return
    if not options.yes:
        raise UsageError("port change requires --yes")
    if not options.name.strip():
        raise UsageError("an exact nonempty mapping name is required")
    if options.port_action == "add":
        try:
            address = ipaddress.ip_address(options.client)
        except ValueError:
            raise UsageError("--client must be a valid IP address") from None
        if getattr(address, "scope_id", None):
            raise UsageError("scoped IPv6 addresses are not supported")
        if not all(1 <= p <= 65535 for p in (options.external_port, options.internal_port)):
            raise UsageError("ports must be between 1 and 65535")


def _output(options, stdout, value, message):
    if options.json:
        print(json.dumps(value, indent=2, ensure_ascii=False), file=stdout)
    else:
        print(message, file=stdout)


def _rules(snapshot):
    rules = snapshot.get("pmRule", [])
    if len(rules) != snapshot.get("count"):
        raise GatewayError("incomplete mapping list; refusing to plan or verify a change")
    names = [rule["desp"] for rule in rules]
    if len(set(names)) != len(names):
        raise GatewayError("ambiguous mapping names; refusing to change a rule")
    return rules


def _same_mapping(actual, expected):
    return all(actual.get(k) == expected.get(k) for k in ("desp", "client", "exPort", "inPort")) and (
        actual.get("protocol", "").upper() == expected.get("protocol", "").upper())


def _unrelated(rules, name):
    return Counter(json.dumps(r, sort_keys=True) for r in rules if r["desp"] != name)


def _port_change(client, options, stdout):
    action, name = options.port_action, options.name
    before = _rules(client.port_mappings())
    current = next((r for r in before if r["desp"] == name), None)
    result = {"action": "port " + action, "name": name, "changed": False, "verified": True}
    if action == "add":
        if current is not None:
            raise GatewayError("mapping already exists; refusing implicit replacement")
        expected = {"desp": name, "client": options.client, "protocol": options.protocol,
                    "exPort": options.external_port, "inPort": options.internal_port}
        client.add_port_mapping(expected)
    else:
        if current is None:
            raise GatewayError("mapping does not exist")
        desired = action == "enable"
        if action != "delete" and bool(current["enable"]) == desired:
            _output(options, stdout, result, "mapping already " + ("enabled" if desired else "disabled"))
            return
        getattr(client, action + "_port_mapping")(name)
    try:
        after = _rules(client.port_mappings())
    except GatewayError:
        raise GatewayError("change submitted but read-back failed; outcome unknown; inspect port list before retrying") from None
    actual = next((r for r in after if r["desp"] == name), None)
    if _unrelated(before, name) != _unrelated(after, name):
        raise GatewayError("gateway changed unrelated mappings; inspect the full list before another change")
    if action == "delete":
        verified = actual is None
    elif action == "add":
        verified = actual is not None and _same_mapping(actual, expected)
    else:
        verified = actual is not None and _same_mapping(actual, current) and bool(actual["enable"]) == desired
    if not verified:
        raise GatewayError("write outcome not verified; inspect port list before retrying")
    result["changed"] = True
    _output(options, stdout, result, "port mapping " + action + " completed and verified")


def _human(command, value):
    if command == "status":
        return "\n".join(f"{label}\t{value[key]}{suffix}" for label, key, suffix in (
            ("CPU", "cpuUsed", "%"), ("System uptime", "sysTime", "s"),
            ("Internet uptime", "upTime", "s"), ("Wired devices", "wcount", ""),
            ("Wireless devices", "wlcount", ""), ("VoIP", "voip", ""), ("iTV", "itv", "")))
    if command == "info":
        return "\n".join(f"{key}\t{item}" for key, item in value.items())
    if command == "devices":
        lines = ["LINK\tNAME\tIP\tTYPE\tBRAND\tMODEL\tONLINE"]
        for key, label in (("pc", "wired"), ("wifi", "wireless")):
            for device in value.get(key, []):
                lines.append("\t".join([label, *[str(device.get(k, "")) for k in (
                    "devName", "ip", "type", "brand", "model", "onlineTime")]]))
        return "\n".join(lines)
    lines = ["NAME\tENABLED\tCLIENT\tPROTOCOL\tEXTERNAL\tINTERNAL"]
    for rule in value.get("pmRule", []):
        lines.append("\t".join(str(rule[k]) for k in ("desp", "enable", "client", "protocol", "exPort", "inPort")))
    return "\n".join(lines)


def _password(options, stdin, environ):
    if options.password_stdin:
        value = stdin.readline(65538)
        if len(value) > 65536:
            raise UsageError("password input is too long")
        value = value.rstrip("\r\n")
        if not value:
            raise UsageError("password input is empty")
        return value
    return environ.get("CTGW_PASSWORD", "")


def run(args=None, *, stdin=None, stdout=None, stderr=None, store=None, environ=None,
        client_factory=GatewayClient, version=__version__):
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    environ = os.environ if environ is None else environ
    try:
        command_parser = parser()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            options = command_parser.parse_args(sys.argv[1:] if args is None else args)
        if options.command in (None, "help"):
            command_parser.print_help(stdout)
            return 0
        if options.command == "version":
            _output(options, stdout, {"version": version, "implementation": "python"}, version)
            return 0
        store = Store() if store is None else store
        if options.command == "doctor":
            try:
                keyring_version = importlib.metadata.version("keyring")
            except importlib.metadata.PackageNotFoundError:
                keyring_version = None
            result = {"python": platform.python_version(), "platform": sys.platform,
                      "keyring_version": keyring_version, "profile_path": str(store.path),
                      "model": "TEWA-1000E", "firmware": "Tianyi_V1.0_JS2011",
                      "gateway_contacted": False}
            _output(options, stdout, result, json.dumps(result, indent=2))
            return 0
        _validate_action(options)
        profile = store.load()
        if options.command == "auth" and options.auth_action in ("status", "logout"):
            if profile is None:
                _output(options, stdout, {"stored": False}, "no stored credentials")
                return 0
            if options.auth_action == "logout":
                store.delete()
                _output(options, stdout, {"stored": False}, "stored credentials deleted")
            else:
                store.password(profile)  # Check availability internally; never print the secret.
                _output(options, stdout, {"url": profile.url, "username": profile.username,
                    "password_storage": "system-keyring"},
                    f"URL\t{profile.url}\nUsername\t{profile.username}\nPassword\tsystem keyring\nProfile\t{store.path}")
            return 0
        url = options.url or environ.get("CTGW_URL") or (profile.url if profile else "http://192.168.1.1")
        username = options.username or environ.get("CTGW_USERNAME") or (profile.username if profile else "")
        password = _password(options, stdin, environ)
        auth_login = options.command == "auth"
        if not password and not auth_login and profile and (
                url.rstrip("/") == profile.url.rstrip("/") and username == profile.username):
            password = store.password(profile)
        if not username or not password:
            raise UsageError("credentials required; use auth login, environment credentials, or --password-stdin")
        try:
            client = client_factory(url, username, password, timeout=options.timeout,
                                    deadline=time.monotonic() + options.timeout)
        except GatewayError as exc:
            raise UsageError(str(exc)) from None
        client.login()
        if auth_login:
            store.save(Profile(url=url, username=username), password)
            _output(options, stdout, {"verified": True, "stored": True}, "credentials verified and stored")
        elif options.command == "reboot":
            client.reboot()
            _output(options, stdout, {"action": "reboot", "requested": True}, "reboot requested")
        elif options.command == "port" and options.port_action != "list":
            _port_change(client, options, stdout)
        else:
            method = "port_mappings" if options.command == "port" else options.command
            value = getattr(client, method)()
            if options.command == "info" and not options.show_sensitive:
                value = {k: v for k, v in value.items() if k not in {
                    "MAC", "ProductSN", "ssid2g", "ssid5g", "wanAcnt"}}
            _output(options, stdout, value, _human(options.command, value))
        return 0
    except _ParserExit as exc:
        return exc.status
    except UsageError as exc:
        print("ctgw: " + str(exc), file=stderr)
        return 2
    except (GatewayError, CredentialError) as exc:
        print("ctgw: " + str(exc), file=stderr)
        return 1
    except (OSError, ValueError, TypeError, KeyError):
        print("ctgw: local operation failed; details withheld to protect credentials", file=stderr)
        return 1
    except KeyboardInterrupt:
        print("ctgw: interrupted; if a change was submitted, inspect state before retrying", file=stderr)
        return 130


def main():
    return run()

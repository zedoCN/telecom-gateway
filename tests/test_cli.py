"""End-to-end CLI requests use a synthetic local gateway and injected credentials."""

import copy
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ctgw.cli import duration, run, UsageError
from ctgw.credentials import CredentialError, Profile
from test_client import gateway, LOGIN, STATUS, INFO, MAPPINGS, WRITE, REBOOT


class FakeStore:
    path = Path("/synthetic/profile.json")

    def __init__(self, profile=None):
        self.profile = profile
        self.secret = "synthetic-password"
        self.saved = 0
        self.reads = 0
        self.loads = 0

    def load(self):
        self.loads += 1
        return self.profile

    def password(self, profile):
        self.reads += 1
        return self.secret

    def save(self, profile, secret):
        self.profile, self.secret = profile, secret
        self.saved += 1

    def delete(self):
        self.profile = None


def rule(name="example", **changes):
    value = {"desp": name, "client": "192.0.2.10", "enable": 1,
             "exPort": 8211, "inPort": 8211, "protocol": "UDP"}
    value.update(changes)
    return value


def setup_mappings(state):
    state["rows"] = [rule(), rule("unrelated", exPort=2222, inPort=22, protocol="TCP")]
    state["writes"] = 0

    def respond(handler, value, status=200):
        body = json.dumps(value).encode()
        handler.send_response(status)
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)

    def read(handler):
        if state.get("read_failure") and state["writes"]:
            respond(handler, {}, 500)
            return
        rows = state["rows"]
        respond(handler, {"count": len(rows) + state.get("count_delta", 0),
                          **{f"pmRule{i}": r for i, r in enumerate(rows, 1)}})

    def write(handler):
        state["writes"] += 1
        form = state["requests"][-1]["form"]
        op, name = form["op"][0], form["srvname"][0]
        if not state.get("ignore_write"):
            if op == "add":
                state["rows"].append(rule(name, client=form["client"][0], protocol=form["protocol"][0],
                                          exPort=int(form["exPort"][0]), inPort=int(form["inPort"][0])))
            elif op == "del":
                state["rows"] = [r for r in state["rows"] if r["desp"] != name]
            else:
                next(r for r in state["rows"] if r["desp"] == name)["enable"] = int(op == "enable")
        if state.get("change_unrelated"):
            next(r for r in state["rows"] if r["desp"] == "unrelated")["inPort"] = 23
        respond(handler, {})

    state["routes"][("GET", MAPPINGS)] = read
    state["routes"][("POST", WRITE)] = write


class CLITests(unittest.TestCase):
    def invoke(self, args, *, state=None, store=None, password="", environ=None, **kwargs):
        output, error = io.StringIO(), io.StringIO()
        env = {} if environ is None else environ
        if state is not None:
            args = ["--url", state["url"], *args]
            env = {"CTGW_USERNAME": "synthetic-user", "CTGW_PASSWORD": "synthetic-password", **env}
        with patch.dict("os.environ", {"NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"}):
            code = run(args, stdin=io.StringIO(password), stdout=output, stderr=error,
                       store=FakeStore() if store is None else store, environ=env, **kwargs)
        return code, output.getvalue(), error.getvalue()

    def test_local_commands_do_not_read_credentials_or_create_client(self):
        for args in ([], ["help"], ["--help"], ["version"], ["--json", "doctor"], ["port", "add", "--help"]):
            with self.subTest(args=args):
                store = FakeStore()
                code, output, error = self.invoke(args, store=store,
                    client_factory=lambda *a, **kw: self.fail("local command contacted gateway"))
                self.assertEqual((code, error), (0, ""))
                self.assertTrue(output)
                self.assertEqual(store.loads, 0)

    def test_invalid_or_unconfirmed_change_fails_before_credentials_and_network(self):
        cases = [["reboot"], ["port", "disable", "--name", "example"],
                 ["port", "delete", "--yes", "--name", " "],
                 ["port", "add", "--yes", "--name", "example", "--client", "bad",
                  "--protocol", "TCP", "--external-port", "1", "--internal-port", "2"],
                 ["port", "enable", "--yes"], ["status", "--json"]]
        for args in cases:
            with self.subTest(args=args):
                store = FakeStore()
                code, output, error = self.invoke(args, store=store,
                    client_factory=lambda *a, **kw: self.fail("invalid command contacted gateway"))
                self.assertEqual(code, 2)
                self.assertEqual(output, "")
                self.assertEqual(store.loads, 0)

    def test_usage_error_does_not_echo_unknown_secret_argument(self):
        code, output, error = self.invoke(["--password", "synthetic-sensitive-argument", "status"])
        self.assertEqual(code, 2)
        self.assertNotIn("synthetic-sensitive-argument", output + error)

    def test_credentials_required(self):
        code, output, error = self.invoke(["status"])
        self.assertEqual(code, 2)
        self.assertIn("credentials required", error)

    def test_status_json_compatibility_and_profile_reuse(self):
        with gateway() as state:
            state["routes"][("GET", STATUS)] = (200, {}, {"cpuUsed": 7, "sysTime": 60})
            store = FakeStore(Profile(state["url"], "synthetic-user"))
            code, output, error = self.invoke(["--json", "status"], store=store)
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output), {"cpuUsed": 7, "scount": 0, "sysTime": 60,
                "upTime": 0, "wcount": 0, "wlcount": 0, "itv": False, "voip": False})
            self.assertEqual(store.reads, 1)

    def test_secret_not_reused_for_different_target_or_user(self):
        store = FakeStore(Profile("http://192.0.2.1", "synthetic-user"))
        for args in (["--url", "http://192.0.2.2", "status"],
                     ["--username", "other-user", "status"]):
            code, _, _ = self.invoke(args, store=store)
            self.assertEqual(code, 2)
        self.assertEqual(store.reads, 0)

    def test_info_redaction_in_json_and_human_output(self):
        with gateway() as state:
            data = {"ProductCls": "synthetic-model", "wifiOnOff": True,
                    **{k: "synthetic-sensitive-" + k for k in (
                        "MAC", "ProductSN", "ssid2g", "ssid5g", "wanAcnt", "unknownSecret")}}
            state["routes"][("GET", INFO)] = (200, {}, data)
            for args in (["info"], ["--json", "info"]):
                code, output, error = self.invoke(args, state=state)
                self.assertEqual((code, error), (0, ""))
                self.assertIn("synthetic-model", output)
                self.assertNotIn("synthetic-sensitive", output)
            code, output, _ = self.invoke(["--json", "info", "--show-sensitive"], state=state)
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["MAC"], data["MAC"])
            self.assertNotIn("unknownSecret", json.loads(output))

    def test_auth_login_verifies_before_save_and_hides_password(self):
        with gateway() as state:
            store = FakeStore()
            args = ["--url", state["url"], "--username", "synthetic-user", "--password-stdin", "--json", "auth", "login"]
            code, output, error = self.invoke(args, store=store, password="synthetic-password\n")
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(store.saved, 1)
            self.assertEqual(store.profile.url, state["url"])
            self.assertNotIn("synthetic-password", output + error)
            state["routes"][("POST", LOGIN)] = (200, {}, b"rejected")
            code, _, _ = self.invoke(args, store=store, password="synthetic-password\n")
            self.assertEqual(code, 1)
            self.assertEqual(store.saved, 1)

    def test_auth_status_and_logout_are_local(self):
        store = FakeStore(Profile("http://192.0.2.1", "synthetic-user"))
        code, output, error = self.invoke(["--json", "auth", "status"], store=store)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output)["password_storage"], "system-keyring")
        self.assertNotIn(store.secret, output)
        self.assertEqual(self.invoke(["auth", "logout"], store=store)[0], 0)
        code, output, _ = self.invoke(["--json", "auth", "status"], store=store)
        self.assertEqual((code, json.loads(output)), (0, {"stored": False}))

    def test_each_exact_mapping_change_has_one_write_and_readback(self):
        commands = [["disable", "--name", "example"], ["enable", "--name", "example"],
                    ["delete", "--name", "example"], ["add", "--name", "new",
                     "--client", "192.0.2.20", "--protocol", "udp", "--external-port", "3000", "--internal-port", "3001"]]
        for command in commands:
            with self.subTest(action=command[0]), gateway() as state:
                setup_mappings(state)
                if command[0] == "enable":
                    state["rows"][0]["enable"] = 0
                original_other = copy.deepcopy(state["rows"][1])
                code, output, error = self.invoke(["--json", "port", *command, "--yes"], state=state)
                self.assertEqual((code, error), (0, ""))
                self.assertTrue(json.loads(output)["verified"])
                self.assertEqual(state["writes"], 1)
                self.assertEqual(sum(r["path"] == MAPPINGS for r in state["requests"]), 2)
                self.assertIn(original_other, state["rows"])

    def test_duplicate_add_unknown_delete_and_idempotent_enable_do_not_write(self):
        for action, name, code_expected in (("add", "example", 1), ("delete", "absent", 1), ("enable", "example", 0)):
            with gateway() as state:
                setup_mappings(state)
                args = ["--json", "port", action, "--name", name, "--yes"]
                if action == "add":
                    args += ["--client", "192.0.2.20", "--protocol", "TCP", "--external-port", "1", "--internal-port", "2"]
                code, _, _ = self.invoke(args, state=state)
                self.assertEqual(code, code_expected)
                self.assertEqual(state["writes"], 0)

    def test_write_result_must_be_readback_verified_without_retries(self):
        for failure in ("ignore_write", "change_unrelated", "read_failure"):
            with self.subTest(failure=failure), gateway() as state:
                setup_mappings(state)
                state[failure] = True
                code, output, error = self.invoke(["--json", "port", "disable", "--name", "example", "--yes"], state=state)
                self.assertEqual(code, 1)
                self.assertEqual(output, "")
                self.assertTrue(error)
                self.assertEqual(state["writes"], 1)

    def test_ambiguous_or_incomplete_list_refuses_write(self):
        for ambiguous in (False, True):
            with gateway() as state:
                setup_mappings(state)
                if ambiguous:
                    state["rows"].append(rule())
                else:
                    state["count_delta"] = 1
                code, _, _ = self.invoke(["port", "delete", "--name", "example", "--yes"], state=state)
                self.assertEqual(code, 1)
                self.assertEqual(state["writes"], 0)

    def test_reboot_reports_only_request_not_recovery(self):
        with gateway() as state:
            code, output, error = self.invoke(["--json", "reboot", "--yes"], state=state)
            self.assertEqual((code, error), (0, ""))
            self.assertEqual(json.loads(output), {"action": "reboot", "requested": True})
            self.assertEqual(sum(r["path"] == REBOOT for r in state["requests"]), 1)

    def test_timeout_syntax(self):
        self.assertEqual(duration("1m30s"), 90)
        self.assertEqual(duration("250ms"), .25)
        for value in ("0", "nan", "-1s", "secret", "1s2bad"):
            with self.assertRaises(UsageError):
                duration(value)


if __name__ == "__main__":
    unittest.main()

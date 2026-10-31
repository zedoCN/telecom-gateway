"""Synthetic credential tests; no test accesses an OS credential service."""

import base64
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

from ctgw.credentials import CredentialError, Profile, Store, _SystemSecrets


class MemorySecrets:
    def __init__(self):
        self.values = {}
        self.fail_write = False
        self.fail_delete = False

    def get_password(self, service, account):
        return self.values.get((service, account))

    def set_password(self, service, account, password):
        if self.fail_write:
            self.fail_write = False
            raise RuntimeError("SENSITIVE_BACKEND_CONTENT")
        self.values[(service, account)] = password

    def delete_password(self, service, account):
        if self.fail_delete:
            raise RuntimeError("SENSITIVE_BACKEND_CONTENT")
        self.values.pop((service, account), None)


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "config" / "profile.json"
        self.secrets = MemorySecrets()
        self.store = Store(self.path, self.secrets)
        self.profile = Profile("http://192.0.2.1", "example-user")

    def write_profile(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(value)

    def assert_no_temporary_files(self):
        self.assertEqual(list(self.path.parent.glob(".profile-*.tmp")), [])

    def test_profile_is_frozen(self):
        with self.assertRaises(FrozenInstanceError):
            self.profile.username = "other"

    def test_missing_profile(self):
        self.assertIsNone(self.store.load())
        self.store.delete()
        self.assertEqual(self.store.path, self.path)

    def test_round_trip_and_metadata_only(self):
        self.store.save(Profile(self.profile.url + "/", self.profile.username), "example-password")
        self.assertEqual(self.store.load(), self.profile)
        self.assertEqual(self.store.password(self.profile), "example-password")
        metadata = self.path.read_text()
        self.assertEqual(json.loads(metadata), {"url": self.profile.url, "username": self.profile.username})
        self.assertNotIn("example-password", metadata)
        self.store.delete()
        self.assertIsNone(self.store.load())
        self.assertEqual(self.secrets.values, {})
        self.assert_no_temporary_files()

    @unittest.skipIf(os.name == "nt", "Windows uses inherited current-user ACLs")
    def test_permissions(self):
        self.store.save(self.profile, "example-password")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)
        self.path.chmod(0o644)
        self.path.parent.chmod(0o755)
        self.store.save(self.profile, "new-password")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_invalid_metadata(self):
        invalid = [
            b"null", b"[]", b'"text"', b"1", b"true", b"{}", b"{",
            b'{"url":"http://192.0.2.1","username":"example-user","password":"SECRET"}',
            b'{"url":"http://192.0.2.1","username":"example-user","username":"duplicate"}',
            b'{"url":"http://192.0.2.1","username":"example-user"} {}',
            b'{"url":null,"username":"example-user"}',
            b'{"url":"http://192.0.2.1","username":false}',
            b'{"url":"http://192.0.2.1","username":""}',
            b'{"url":"file:///tmp/gateway","username":"example-user"}',
            b'{"url":"http://secret-user:secret-password@192.0.2.1","username":"example-user"}',
            b'{"url":"http://192.0.2.1","username":"SENSITIVE\\nUSERNAME"}',
            b"\xff", b" " * (64 * 1024 + 1),
        ]
        for value in invalid:
            with self.subTest(value=value[:30]):
                self.write_profile(value)
                with self.assertRaises(CredentialError) as caught:
                    self.store.load()
                self.assertEqual(str(caught.exception), "invalid stored profile")

    def test_invalid_save_leaves_existing_credentials(self):
        self.store.save(self.profile, "old-password")
        previous = self.path.read_bytes()
        invalid = [
            Profile("", "example-user"), Profile(self.profile.url, ""),
            Profile("http://192.0.2.1:bad", "example-user"),
            Profile("http://192.0.2.1?password=SECRET", "example-user"),
            Profile("http://192.0.2.1/#fragment", "example-user"),
            Profile("http://192.0.2.1/path with space", "example-user"),
            Profile(12, "example-user"), Profile(self.profile.url, None),
        ]
        for profile in invalid:
            with self.subTest(profile=profile):
                with self.assertRaises(CredentialError):
                    self.store.save(profile, "new-password")
                self.assertEqual(self.path.read_bytes(), previous)
                self.assertEqual(self.store.password(self.profile), "old-password")
        for password in ("", None, 1):
            with self.assertRaises(CredentialError):
                self.store.save(self.profile, password)
        self.assert_no_temporary_files()

    def test_oversize_profile_is_rejected_before_mutation(self):
        with self.assertRaises(CredentialError):
            self.store.save(Profile(self.profile.url, "x" * (64 * 1024)), "example-password")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.secrets.values, {})

    def test_write_failure_preserves_previous_profile_and_password(self):
        self.store.save(self.profile, "old-password")
        previous = self.path.read_bytes()
        self.secrets.fail_write = True
        with self.assertRaises(CredentialError) as caught:
            self.store.save(self.profile, "new-password")
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.store.password(self.profile), "old-password")
        self.assert_no_temporary_files()

    def test_partial_keyring_write_failure_is_rolled_back(self):
        self.store.save(self.profile, "old-password")
        original = self.secrets.set_password
        attempted = False

        def partial_write(service, account, password):
            nonlocal attempted
            original(service, account, password)
            if not attempted:
                attempted = True
                raise RuntimeError("SENSITIVE_BACKEND_CONTENT")

        with patch.object(self.secrets, "set_password", side_effect=partial_write):
            with self.assertRaises(CredentialError):
                self.store.save(self.profile, "new-password")
        self.assertEqual(self.store.password(self.profile), "old-password")
        self.assert_no_temporary_files()

    def test_replace_failure_restores_previous_password(self):
        self.store.save(self.profile, "old-password")
        previous = self.path.read_bytes()
        with patch("ctgw.credentials.os.replace", side_effect=OSError("SENSITIVE_CONTENT")):
            with self.assertRaises(CredentialError) as caught:
                self.store.save(self.profile, "new-password")
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(self.store.password(self.profile), "old-password")
        self.assert_no_temporary_files()

    def test_replace_failure_removes_new_secret_and_preserves_other_profile(self):
        self.store.save(self.profile, "old-password")
        other = Profile("http://192.0.2.2", "other-example-user")
        with patch("ctgw.credentials.os.replace", side_effect=OSError()):
            with self.assertRaises(CredentialError):
                self.store.save(other, "new-password")
        self.assertEqual(self.store.load(), self.profile)
        self.assertEqual(self.store.password(self.profile), "old-password")
        self.assertEqual(len(self.secrets.values), 1)
        self.assert_no_temporary_files()

    def test_delete_failure_does_not_claim_success(self):
        self.store.save(self.profile, "example-password")
        self.secrets.fail_delete = True
        with self.assertRaises(CredentialError) as caught:
            self.store.delete()
        self.assertNotIn("SENSITIVE", str(caught.exception))
        self.assertEqual(self.store.load(), self.profile)
        self.assertEqual(self.store.password(self.profile), "example-password")

    def test_profile_unlink_failure_restores_secret(self):
        self.store.save(self.profile, "example-password")
        with patch.object(Path, "unlink", side_effect=PermissionError("SENSITIVE_CONTENT")):
            with self.assertRaises(CredentialError):
                self.store.delete()
        self.assertEqual(self.store.load(), self.profile)
        self.assertEqual(self.store.password(self.profile), "example-password")

    def test_missing_secret_is_explicit_and_metadata_can_be_removed(self):
        self.write_profile(json.dumps({"url": self.profile.url, "username": self.profile.username}).encode())
        with self.assertRaisesRegex(CredentialError, "auth login"):
            self.store.password(self.profile)
        self.store.delete()
        self.assertIsNone(self.store.load())

    def test_go_macos_encodings_and_plain_legacy_secret(self):
        account = self.profile.username + "@" + self.profile.url
        variants = [
            "example-password",
            "go-keyring-base64:" + base64.b64encode("example-密码".encode()).decode(),
            "go-keyring-encoded:" + "example-密码".encode().hex(),
        ]
        with patch("ctgw.credentials.sys.platform", "darwin"):
            for value in variants:
                self.secrets.values[("ctgw", account)] = value
                expected = "example-password" if value == "example-password" else "example-密码"
                self.assertEqual(self.store.password(self.profile), expected)
            self.store.save(self.profile, "go-keyring-base64:literal-password")
            self.assertTrue(self.secrets.values[("ctgw", account)].startswith("go-keyring-base64:"))
            self.assertEqual(self.store.password(self.profile), "go-keyring-base64:literal-password")

    def test_bad_macos_encoding_does_not_echo_value(self):
        account = self.profile.username + "@" + self.profile.url
        with patch("ctgw.credentials.sys.platform", "darwin"):
            for value in ("go-keyring-base64:SENSITIVE!!!", "go-keyring-encoded:SENSITIVE", "go-keyring-base64:/w=="):
                self.secrets.values[("ctgw", account)] = value
                with self.assertRaises(CredentialError) as caught:
                    self.store.password(self.profile)
                self.assertNotIn("SENSITIVE", str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)

    def test_default_paths_follow_go_user_config_dir(self):
        home = Path(self.directory.name) / "home"
        with patch("ctgw.credentials.Path.home", return_value=home), patch.dict(os.environ, {}, clear=True):
            with patch("ctgw.credentials.sys.platform", "darwin"):
                self.assertEqual(Store().path, home / "Library/Application Support/ctgw/profile.json")
            with patch("ctgw.credentials.sys.platform", "linux"):
                self.assertEqual(Store().path, home / ".config/ctgw/profile.json")
                with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home / "xdg")}):
                    self.assertEqual(Store().path, home / "xdg/ctgw/profile.json")
            with patch("ctgw.credentials.sys.platform", "win32"):
                with self.assertRaises(CredentialError):
                    Store()
                with patch.dict(os.environ, {"APPDATA": str(home / "AppData/Roaming")}):
                    self.assertEqual(Store().path, home / "AppData/Roaming/ctgw/profile.json")

    def test_help_style_import_and_metadata_do_not_import_keyring(self):
        with patch("ctgw.credentials.importlib.import_module", side_effect=AssertionError("must stay lazy")):
            store = Store(self.path)
            self.assertIsNone(store.load())
        source_root = Path(sys.modules["ctgw.credentials"].__file__).resolve().parent.parent
        script = (
            "import sys; sys.path.insert(0, sys.argv[1]); import ctgw.credentials; "
            "assert not any(n == 'keyring' or n.startswith('keyring.') for n in sys.modules)"
        )
        subprocess.run([sys.executable, "-c", script, str(source_root)], check=True, capture_output=True)

    def test_backend_is_direct_known_system_backend(self):
        for platform, module, class_name in (
            ("darwin", "keyring.backends.macOS", "Keyring"),
            ("win32", "keyring.backends.Windows", "WinVaultKeyring"),
            ("linux", "keyring.backends.SecretService", "Keyring"),
        ):
            fake_backend = types.SimpleNamespace(priority=5, get_password=lambda service, account: "example-password")
            fake_module = types.SimpleNamespace(**{class_name: lambda: fake_backend})
            with self.subTest(platform=platform), patch("ctgw.credentials.sys.platform", platform), patch("ctgw.credentials.importlib.import_module", return_value=fake_module) as imported:
                secrets = _SystemSecrets()
                self.assertEqual(secrets.get_password("ctgw", "example-account"), "example-password")
                imported.assert_called_once_with(module)
                if platform == "linux":
                    self.assertEqual(fake_backend.scheme, "default")
                    self.assertEqual(fake_backend.preferred_collection, "/org/freedesktop/secrets/collection/login")

    def test_backend_unavailable_never_falls_back(self):
        with patch("ctgw.credentials.importlib.import_module", side_effect=ImportError("SENSITIVE_BACKEND_CONTENT")) as imported:
            with self.assertRaises(CredentialError) as caught:
                _SystemSecrets().get_password("ctgw", "example-account")
            self.assertNotIn("SENSITIVE", str(caught.exception))
            self.assertEqual(imported.call_count, 1)


if __name__ == "__main__":
    unittest.main()

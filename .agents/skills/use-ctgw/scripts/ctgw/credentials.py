"""Profile metadata and passwords held by the current user's OS keyring.

Only metadata is written to disk. POSIX modes are enforced on POSIX systems;
Windows directory protection relies on the current user's inherited ACLs.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
from urllib.parse import urlsplit


_SERVICE = "ctgw"
_MAX_PROFILE_BYTES = 64 * 1024
_BASE64_PREFIX = "go-keyring-base64:"
_HEX_PREFIX = "go-keyring-encoded:"


class CredentialError(Exception):
    """A credential operation failed; messages never contain stored values."""


@dataclass(frozen=True)
class Profile:
    url: str
    username: str


def _profile(profile: Profile) -> Profile:
    if not isinstance(profile, Profile):
        raise CredentialError("invalid stored profile")
    if not isinstance(profile.url, str) or not isinstance(profile.username, str):
        raise CredentialError("invalid stored profile")
    if not profile.username.strip() or any(ord(c) < 32 or ord(c) == 127 for c in profile.username):
        raise CredentialError("gateway username is required and must not contain control characters")
    try:
        parts = urlsplit(profile.url)
        valid = (
            parts.scheme in ("http", "https")
            and bool(parts.hostname)
            and parts.username is None
            and parts.password is None
            and not parts.query
            and not parts.fragment
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in profile.url)
        )
        # Accessing port also checks malformed ports and IPv6 authorities.
        parts.port
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise CredentialError("gateway URL must be an HTTP or HTTPS URL without credentials, query or fragment")
    return Profile(profile.url.rstrip("/"), profile.username)


def _default_path() -> Path:
    if sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise CredentialError("cannot locate the current user's configuration directory")
        root = Path(appdata)
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "ctgw" / "profile.json"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


class _SystemSecrets:
    """Choose a known system backend directly, without plugin/fallback chains."""

    def __init__(self):
        self._backend = None

    def _get_backend(self):
        if self._backend is None:
            try:
                if sys.platform == "darwin":
                    module, name = "keyring.backends.macOS", "Keyring"
                elif sys.platform == "win32":
                    module, name = "keyring.backends.Windows", "WinVaultKeyring"
                elif sys.platform.startswith(("linux", "freebsd", "openbsd", "netbsd", "dragonfly")):
                    module, name = "keyring.backends.SecretService", "Keyring"
                else:
                    raise RuntimeError("unsupported platform")
                backend = getattr(importlib.import_module(module), name)()
                if backend.priority <= 0:
                    raise RuntimeError("unavailable backend")
                if module == "keyring.backends.SecretService":
                    # Go used this collection and these exact attribute names.
                    backend.preferred_collection = "/org/freedesktop/secrets/collection/login"
                    backend.scheme = "default"
                self._backend = backend
            except Exception:
                raise CredentialError("system keyring unavailable; install keyring and enable the OS credential service") from None
        return self._backend

    def get_password(self, service, account):
        return self._get_backend().get_password(service, account)

    def set_password(self, service, account, secret):
        self._get_backend().set_password(service, account, secret)

    def delete_password(self, service, account):
        self._get_backend().delete_password(service, account)


class Store:
    """An injectable keyring-style store using get/set/delete_password methods."""

    def __init__(self, profile_path: Path | None = None, secrets=None):
        self._path = Path(profile_path) if profile_path is not None else _default_path()
        self._secrets = secrets if secrets is not None else _SystemSecrets()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Profile | None:
        try:
            with self._path.open("rb") as stream:
                data = stream.read(_MAX_PROFILE_BYTES + 1)
        except FileNotFoundError:
            return None
        except OSError:
            raise CredentialError("cannot read stored profile") from None
        try:
            if len(data) > _MAX_PROFILE_BYTES:
                raise ValueError("profile too large")
            value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object)
            if not isinstance(value, dict) or set(value) != {"url", "username"}:
                raise ValueError("invalid fields")
            return _profile(Profile(value["url"], value["username"]))
        except (ValueError, TypeError, RecursionError, CredentialError):
            raise CredentialError("invalid stored profile") from None

    @staticmethod
    def _account(profile: Profile) -> str:
        return profile.username + "@" + profile.url.rstrip("/")

    def _read_secret(self, account):
        try:
            value = self._secrets.get_password(_SERVICE, account)
            if value is not None and not isinstance(value, str):
                raise TypeError("invalid secret")
            return value
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("cannot read password from system keyring") from None

    def _write_secret(self, account, value):
        try:
            self._secrets.set_password(_SERVICE, account, value)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("cannot store password in system keyring") from None

    def _delete_secret(self, account):
        try:
            self._secrets.delete_password(_SERVICE, account)
        except CredentialError:
            raise
        except Exception:
            raise CredentialError("cannot delete password from system keyring") from None

    def _restore(self, account, previous):
        try:
            if previous is not None:
                self._write_secret(account, previous)
            elif self._read_secret(account) is not None:
                self._delete_secret(account)
        except CredentialError:
            raise CredentialError("credential operation failed and the previous keyring entry could not be restored") from None

    def save(self, profile: Profile, password: str):
        profile = _profile(profile)
        if not isinstance(password, str) or not password:
            raise CredentialError("password is required")
        try:
            raw_password = password
            if sys.platform == "darwin":
                raw_password = _BASE64_PREFIX + base64.b64encode(password.encode("utf-8")).decode("ascii")
            data = (json.dumps({"url": profile.url, "username": profile.username}, indent=2) + "\n").encode("utf-8")
        except UnicodeError:
            raise CredentialError("profile and password must contain valid Unicode") from None
        if len(data) > _MAX_PROFILE_BYTES:
            raise CredentialError("stored profile exceeds the size limit")
        account = self._account(profile)
        previous = self._read_secret(account)
        temporary = None
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if os.name != "nt":
                self._path.parent.chmod(0o700)
            fd, name = tempfile.mkstemp(prefix=".profile-", suffix=".tmp", dir=self._path.parent)
            temporary = Path(name)
            with os.fdopen(fd, "wb") as stream:
                if os.name != "nt":
                    os.fchmod(stream.fileno(), 0o600)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                self._write_secret(account, raw_password)
                os.replace(temporary, self._path)
            except (CredentialError, OSError):
                self._restore(account, previous)
                raise
        except OSError:
            raise CredentialError("cannot save stored profile") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def password(self, profile: Profile) -> str:
        profile = _profile(profile)
        value = self._read_secret(self._account(profile))
        if not value:
            raise CredentialError("no password in system keyring; run auth login")
        if sys.platform == "darwin":
            try:
                if value.startswith(_BASE64_PREFIX):
                    value = base64.b64decode(value[len(_BASE64_PREFIX):], validate=True).decode("utf-8")
                elif value.startswith(_HEX_PREFIX):
                    value = binascii.unhexlify(value[len(_HEX_PREFIX):]).decode("utf-8")
            except (ValueError, UnicodeError, binascii.Error):
                raise CredentialError("invalid password encoding in system keyring; run auth login") from None
        if not value:
            raise CredentialError("no password in system keyring; run auth login")
        return value

    def delete(self):
        profile = self.load()
        if profile is None:
            return
        account = self._account(profile)
        previous = self._read_secret(account)
        try:
            if previous is not None:
                self._delete_secret(account)
            self._path.unlink(missing_ok=True)
        except (CredentialError, OSError):
            self._restore(account, previous)
            raise CredentialError("cannot delete stored credentials") from None

"""Test Skill contents, offline operation, reproducibility, and install boundaries."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile


REPOSITORY = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("skill_bundle", REPOSITORY / "scripts" / "skill_bundle.py")
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class SkillBundleTests(unittest.TestCase):
    def source_copy(self, root):
        source = root / "source"
        shutil.copytree(bundle.CANONICAL_SKILL, source,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # A synthetic copy makes the tests independent of concurrent documentation edits.
        if not (source / "LICENSE").exists():
            (source / "LICENSE").write_bytes((REPOSITORY / "LICENSE").read_bytes())
        return source

    def make_symlink(self, link, target, *, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (NotImplementedError, OSError) as error:
            self.skipTest(f"symlinks are unavailable on this platform: {type(error).__name__}")

    def test_pack_reproducible_whitelisted_contents_and_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            junk = ("profiles/default.json", "credentials/password.txt", ".git/config",
                    "scripts/ctgw/__pycache__/cli.pyc", "scripts/ctgw/.venv/secret.py",
                    "scripts/ctgw/package.egg-info/secret.py", "scripts/ctgw/venv/secret.py",
                    "scripts/ctgw.pyc", "bin/ctgw", "private.txt")
            for relative in junk:
                path = source / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("synthetic private runtime data", encoding="utf-8")
            (source / "references" / "nested").mkdir()
            (source / "references" / "nested" / "extra.md").write_text("synthetic reference\n", encoding="utf-8")
            output, checksum = bundle.pack(root / "first.zip", source=source)
            second, _ = bundle.pack(root / "second.zip", source=source)
            self.assertEqual(output.read_bytes(), second.read_bytes())
            expected_hash = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(checksum.read_text(encoding="ascii"), f"{expected_hash}  first.zip\n")
            approved = dict(bundle.bundle_files(source))
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.namelist(), ["use-ctgw/" + name for name in sorted(approved)])
                for entry in archive.infolist():
                    relative = entry.filename.removeprefix("use-ctgw/")
                    self.assertEqual(archive.read(entry), approved[relative])
                    self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual((entry.external_attr >> 16) & 0o777, 0o644)
                self.assertTrue(set(bundle.REQUIRED_FILES).issubset(approved))
                for relative in junk:
                    self.assertNotIn("use-ctgw/" + relative, archive.namelist())

    def test_extracted_bundle_runs_independently_offline(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            output, _ = bundle.pack(root / "skill.zip", source=source)
            unpacked = root / "outside-repository"
            with zipfile.ZipFile(output) as archive:
                archive.extractall(unpacked)
            entrypoint = unpacked / "use-ctgw" / "scripts" / "ctgw.py"
            home = root / "isolated-home"
            home.mkdir()
            environment = dict(os.environ)
            environment.pop("PYTHONPATH", None)
            environment.update({"HOME": str(home), "USERPROFILE": str(home),
                "APPDATA": str(home / "AppData" / "Roaming"), "LOCALAPPDATA": str(home / "AppData" / "Local"),
                "XDG_CONFIG_HOME": str(home / "config"), "PYTHONDONTWRITEBYTECODE": "1"})
            for arguments in (["help"], ["version"], ["--json", "doctor"]):
                result = subprocess.run([sys.executable, str(entrypoint), *arguments], cwd=unpacked,
                    env=environment, capture_output=True, text=True, timeout=15, check=False)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.strip())
                if "doctor" in arguments:
                    self.assertIsInstance(json.loads(result.stdout), dict)
            self.assertFalse(any(unpacked.rglob("*.pyc")))
            self.assertFalse(any(home.rglob("profiles.json")))

    def test_install_layout_and_repeat_refuses_to_replace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            destination = root / "new" / "skills"
            installed = bundle.install(destination, source=source)
            self.assertEqual(installed, destination / "use-ctgw")
            for relative, contents in bundle.bundle_files(source):
                self.assertEqual((installed / relative).read_bytes(), contents)
            marker = installed / "SKILL.md"
            marker.write_text("keep existing installation\n", encoding="utf-8")
            with self.assertRaises(bundle.BundleError):
                bundle.install(destination, source=source)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep existing installation\n")
            self.assertEqual(sorted(path.name for path in destination.iterdir()), ["use-ctgw"])

    def test_default_install_destination_uses_agents_skills(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            with patch.object(Path, "home", return_value=root / "home"):
                installed = bundle.install(source=source)
            self.assertEqual(installed, root / "home" / ".agents" / "skills" / "use-ctgw")

    def test_existing_empty_directory_or_file_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            destination = root / "skills"
            target = destination / "use-ctgw"
            target.mkdir(parents=True)
            with self.assertRaises(bundle.BundleError):
                bundle.install(destination, source=source)
            self.assertTrue(target.is_dir())
            self.assertEqual(list(target.iterdir()), [])
            target.rmdir()
            target.write_bytes(b"keep existing file")
            with self.assertRaises(bundle.BundleError):
                bundle.install(destination, source=source)
            self.assertEqual(target.read_bytes(), b"keep existing file")

    def test_source_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            linked_source = root / "linked-source"
            self.make_symlink(linked_source, source, directory=True)
            with self.assertRaises(bundle.BundleError):
                bundle.pack(root / "rejected.zip", source=linked_source)
            (source / "references" / "linked.md").symlink_to(source / "SKILL.md")
            with self.assertRaises(bundle.BundleError):
                bundle.install(root / "skills", source=source)
            self.assertFalse((root / "skills").exists())

    def test_target_symlink_including_dangling_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            destination = root / "skills"
            destination.mkdir()
            missing = root / "missing"
            target = destination / "use-ctgw"
            self.make_symlink(target, missing, directory=True)
            with self.assertRaises(bundle.BundleError):
                bundle.install(destination, source=source)
            self.assertTrue(target.is_symlink())
            self.assertFalse(missing.exists())
            target.unlink()
            actual = root / "existing"
            actual.mkdir()
            self.make_symlink(target, actual, directory=True)
            with self.assertRaises(bundle.BundleError):
                bundle.install(destination, source=source)
            self.assertTrue(target.is_symlink())
            self.assertEqual(list(actual.iterdir()), [])

    def test_missing_required_file_rejected_without_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.source_copy(root)
            (source / "scripts" / "ctgw" / "client.py").unlink()
            with self.assertRaises(bundle.BundleError):
                bundle.pack(root / "output.zip", source=source)
            self.assertFalse((root / "output.zip").exists())


if __name__ == "__main__":
    unittest.main()

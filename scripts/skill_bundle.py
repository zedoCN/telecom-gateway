"""Build or install the complete, offline use-ctgw Agent Skill."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import zipfile


SKILL_NAME = "use-ctgw"
CANONICAL_SKILL = Path(__file__).resolve().parents[1] / ".agents" / "skills" / SKILL_NAME
REQUIRED_FILES = (
    "SKILL.md", "LICENSE", "agents/openai.yaml", "scripts/ctgw.py",
    "scripts/ctgw/__init__.py", "scripts/ctgw/__main__.py", "scripts/ctgw/cli.py",
    "scripts/ctgw/client.py", "scripts/ctgw/credentials.py", "scripts/ctgw/models.py",
)
_EXCLUDED_DIRS = {
    "__pycache__", "venv", "env", "node_modules", "build", "dist", "profiles", "profile",
    "credentials", "private",
}


class BundleError(Exception):
    """A safe distribution failure without including file contents."""


def _excluded_directory(name):
    lowered = name.lower()
    return (name.startswith(".") or lowered in _EXCLUDED_DIRS
            or lowered.endswith((".egg-info", ".dist-info")))


def bundle_files(source=CANONICAL_SKILL):
    """Read only approved skill files, rejecting symlinks before copying data."""
    source = Path(source)
    if source.is_symlink() or not source.is_dir():
        raise BundleError("skill source must be a real directory, not a symlink")
    candidates = set()
    for directory, directories, files in os.walk(source, followlinks=False):
        parent = Path(directory)
        for name in directories + files:
            if (parent / name).is_symlink():
                raise BundleError("skill source contains a symlink")
        directories[:] = [name for name in directories if not _excluded_directory(name)]
        for name in files:
            path = parent / name
            relative = path.relative_to(source)
            if (relative.as_posix() in REQUIRED_FILES
                    or (relative.parts[0] == "references" and path.suffix == ".md")
                    or (relative.parts[:2] == ("scripts", "ctgw") and path.suffix == ".py")):
                if not path.is_file():
                    raise BundleError("approved skill source is not a regular file")
                candidates.add(relative.as_posix())
    if not set(REQUIRED_FILES).issubset(candidates):
        raise BundleError("skill source is missing required distribution files")
    result = []
    for relative in sorted(candidates):
        path = source / relative
        # Recheck at read time; never intentionally dereference a source symlink.
        if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
            raise BundleError("approved skill source is not a regular file")
        result.append((relative, path.read_bytes()))
    return result


def _temporary_file(parent):
    descriptor, name = tempfile.mkstemp(prefix=".use-ctgw-", dir=parent)
    os.close(descriptor)
    return Path(name)


def pack(output, *, source=CANONICAL_SKILL):
    """Write a reproducible ZIP plus a sibling .zip.sha256 checksum file."""
    files = bundle_files(source)
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    checksum = output.with_name(output.name + ".sha256")
    temporary = _temporary_file(output.parent)
    temporary_checksum = None
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative, contents in files:
                entry = zipfile.ZipInfo(f"{SKILL_NAME}/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(entry, contents, compresslevel=9)
        digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
        temporary_checksum = _temporary_file(output.parent)
        temporary_checksum.write_text(f"{digest}  {output.name}\n", encoding="ascii")
        os.replace(temporary, output)
        os.replace(temporary_checksum, checksum)
        return output, checksum
    finally:
        temporary.unlink(missing_ok=True)
        if temporary_checksum is not None:
            temporary_checksum.unlink(missing_ok=True)


def install(destination=None, *, source=CANONICAL_SKILL):
    """Install a complete skill through staging; never replace an existing target."""
    destination = Path(destination).expanduser() if destination is not None else Path.home() / ".agents" / "skills"
    target = destination / SKILL_NAME
    if destination.is_symlink() or os.path.lexists(target):
        raise BundleError("skill destination already exists or is a symlink; nothing was replaced")
    files = bundle_files(source)
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".use-ctgw-", dir=destination))
    try:
        staging.chmod(0o755)
        for relative, contents in files:
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contents)
            path.chmod(0o644)
        if os.path.lexists(target):
            raise BundleError("skill destination already exists; nothing was replaced")
        staging.rename(target)
        return target
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack_command = commands.add_parser("pack", help="create the complete offline Skill ZIP")
    pack_command.add_argument("--output", type=Path, default=Path("dist/use-ctgw.zip"))
    install_command = commands.add_parser("install", help="install without replacing an existing Skill")
    install_command.add_argument("--destination", type=Path, default=None,
                                 help="Skill root (default: ~/.agents/skills)")
    options = parser.parse_args(argv)
    try:
        if options.command == "pack":
            output, checksum = pack(options.output)
            print(f"Created {output}\nSHA256 {checksum}")
        else:
            print(f"Installed {install(options.destination)}")
    except (BundleError, OSError, ValueError, zipfile.BadZipFile):
        # Paths can contain private data; failures need no raw filesystem exception.
        print("Skill distribution failed: check required source files and an unused destination.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

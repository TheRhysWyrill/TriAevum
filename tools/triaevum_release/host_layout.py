"""Host storage policy; import and runtime code consume paths, not sandbox rules."""

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Mapping


FLATPAK_ID = "io.github.coccofresco.TriAevum"
APPIMAGE_PAYLOAD = ("usr", "lib", "triaevum")
# Beside a portable AppImage this folder holds what the shared XDG root holds,
# so copying the folder that contains the AppImage carries the installation.
PORTABLE_DIRECTORY = "TriAevum"


@dataclass(frozen=True)
class HostLayout:
    package: Path
    activation: Path
    use_file_portal: bool = False

    @property
    def data(self) -> Path:
        return self.activation / "data"


def installation_state(installation: Path, platform: str | None = None) -> Path:
    """Forge's launch profile and activation journal for an installation.

    The Windows installation root holds only the executables, README.md and
    LICENSE, so they live in its data/ folder (the runtime looks there too).
    """
    platform = sys.platform if platform is None else platform
    return installation / "data" if platform == "win32" else installation


def appimage_root(package: Path, appdir: str = "") -> Path | None:
    """Return the AppDir that owns `package`, or None outside an AppImage.

    The layout is authoritative, the environment is only corroboration: a
    payload launched without `APPDIR` (direct binary, sanitized environment,
    wrapper) must still keep user data outside the mounted package, otherwise
    every prepared title, save and cache is discarded when the mount goes away.
    """
    candidates = []
    if appdir and Path(appdir).is_absolute():
        candidates.append(Path(appdir).resolve())
    if tuple(package.parts[-len(APPIMAGE_PAYLOAD):]) == APPIMAGE_PAYLOAD:
        candidates.append(Path(*package.parts[:-len(APPIMAGE_PAYLOAD)]))
    for candidate in candidates:
        if candidate == Path(candidate.anchor) or not package.is_relative_to(candidate):
            continue
        return candidate
    return None


def _shared_activation(env: Mapping[str, str]) -> Path | None:
    """The per-user activation root, or None without an absolute home."""
    data_home = env.get("XDG_DATA_HOME", "")
    if not data_home or not Path(data_home).is_absolute():
        home = env.get("HOME", "")
        if not home or not Path(home).is_absolute():
            return None
        data_home = str(Path(home) / ".local/share")
    return (Path(data_home) / PORTABLE_DIRECTORY).resolve()


def portable_activation(env: Mapping[str, str]) -> Path | None:
    """Storage beside the AppImage file, or None when the host did not name it.

    Only the type-2 runtime's `APPIMAGE` names the file the user actually keeps:
    the mounted AppDir is temporary, so a launch that cannot name its AppImage
    (a direct payload binary, an AppRun from an extracted AppDir) keeps the
    shared root.
    """
    appimage = env.get("APPIMAGE", "")
    if not appimage or not Path(appimage).is_absolute():
        return None
    parent = Path(appimage).resolve().parent
    if not parent.is_dir():
        return None
    return parent / PORTABLE_DIRECTORY


def _writable_directory(path: Path) -> bool:
    try:
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    except OSError:
        return False


def _appimage_layout(package: Path, appdir: Path, env: Mapping[str, str]) -> HostLayout:
    """Portable beside the AppImage when possible, else the shared XDG root.

    A writable folder beside the AppImage is the default, so a copy on another
    drive or machine keeps its prepared title, saves and settings. The shared
    root stays in charge where that folder cannot be written (read-only media,
    a system-wide location) and for a user who already installed there:
    starting a second, empty installation would look like lost saves.
    """
    shared = _shared_activation(env)
    if shared is not None and shared.is_relative_to(appdir):
        raise ValueError("AppImage activation must be outside the read-only package")
    portable = portable_activation(env)
    if portable is not None and not portable.is_relative_to(appdir):
        if _writable_directory(portable):
            return HostLayout(package, portable)
        if (shared is None or not shared.is_dir()) and _writable_directory(portable.parent):
            return HostLayout(package, portable)
    if shared is None:
        raise ValueError("AppImage requires an absolute HOME or XDG_DATA_HOME")
    return HostLayout(package, shared)


def for_package(package: Path, *, environ: Mapping[str, str] | None = None,
                platform: str | None = None) -> HostLayout:
    env = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    package = package.resolve()
    appdir = appimage_root(package, env.get("APPDIR", ""))
    if platform == "linux" and appdir is not None and package.is_relative_to(appdir):
        return _appimage_layout(package, appdir, env)
    if platform != "linux" or env.get("FLATPAK_ID") != FLATPAK_ID:
        return HostLayout(package, package)
    data_home = env.get("XDG_DATA_HOME", "")
    if not data_home or not Path(data_home).is_absolute():
        raise ValueError("Flatpak did not provide an absolute XDG_DATA_HOME")
    activation = (Path(data_home) / "TriAevum").resolve()
    if activation.is_relative_to(package):
        raise ValueError("Flatpak activation must be outside the read-only package")
    return HostLayout(package, activation, use_file_portal=True)

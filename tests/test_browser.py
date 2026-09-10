"""Opening a URL from WSL (:mod:`qalpha.live.browser`).

The bug: pressing **Log in to Zerodha** printed ``gio: …: Operation not supported`` and nothing
opened, while the page said Kite had been opened and the user waited for a redirect that was never
coming. ``webbrowser.open`` asks a desktop for its default handler; inside WSL there is neither.

Two properties carry this file. **The `&` in a Kite login URL must survive** — ``?v=3&api_key=…``
truncates at the ampersand under any shell that reads it as a separator, and a login URL missing its
api_key fails in a way that looks like a bad key. And **the result must be truthful**, because every
caller's job is to say "I could not open your browser, here is the link" rather than to claim it did.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qalpha.live import browser

KITE = "https://kite.zerodha.com/connect/login?v=3&api_key=d0lr3pdceh51lgeb"


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    seen: list[list[str]] = []

    def _run(argv: list[str]) -> bool:
        seen.append(argv)
        return True

    monkeypatch.setattr(browser, "_run", _run)
    return seen


# --- detection ------------------------------------------------------------------------------------
def test_the_env_var_is_enough(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-24.04")
    assert browser.is_wsl() is True


def test_the_kernel_string_is_checked_when_the_env_var_is_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A service or a stripped shell may not carry WSL_DISTRO_NAME, and is still inside WSL."""
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    version = tmp_path / "version"
    version.write_text("Linux version 6.6.87.2-microsoft-standard-WSL2", encoding="utf-8")
    monkeypatch.setattr(browser, "Path", lambda p: version)
    assert browser.is_wsl() is True


def test_a_plain_linux_box_is_not_wsl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    version = tmp_path / "version"
    version.write_text("Linux version 6.1.0-generic (Debian)", encoding="utf-8")
    monkeypatch.setattr(browser, "Path", lambda p: version)
    assert browser.is_wsl() is False


def test_an_unreadable_proc_version_is_not_wsl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("WSL_DISTRO_NAME", raising=False)
    monkeypatch.setattr(browser, "Path", lambda p: tmp_path / "missing")
    assert browser.is_wsl() is False


# --- the URL survives -----------------------------------------------------------------------------
def test_the_ampersand_in_a_kite_login_url_is_never_split(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    """THE ONE THAT MATTERS. A login URL truncated at `&` fails as if the key were wrong."""
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    assert browser.open_url(KITE) is True
    argv = calls[0]
    assert argv[0] == "powershell.exe"
    # One argv element carrying the whole URL, single-quoted so PowerShell cannot read the `&`
    # as a command separator. This is why it is not `cmd.exe /c start`, where it would truncate.
    command = argv[-1]
    assert command == f"Start-Process '{KITE}'"
    assert "api_key=d0lr3pdceh51lgeb" in command


def test_an_apostrophe_in_the_url_cannot_break_out_of_the_quoting(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    browser.open_url("https://x.test/?q=it's")
    assert calls[0][-1] == "Start-Process 'https://x.test/?q=it''s'"


def test_no_shell_is_involved(monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]) -> None:
    """Everything goes as a fixed argv list, so nothing in a URL can be executed."""
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    browser.open_url("https://x.test/?a=1;rm%20-rf")
    assert all(isinstance(part, str) for part in calls[0])
    assert len(calls[0]) == 4, "powershell.exe -NoProfile -Command <one command>"


# --- order of preference --------------------------------------------------------------------------
def test_wslview_is_preferred_when_it_is_installed(
    monkeypatch: pytest.MonkeyPatch, calls: list[list[str]]
) -> None:
    """The tool built for this handles quoting and path translation better than we can."""
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: "/usr/bin/wslview")
    assert browser.open_url(KITE) is True
    assert calls == [["/usr/bin/wslview", KITE]]


def test_powershell_is_tried_when_wslview_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed is not the same as working."""
    tried: list[str] = []

    def _run(argv: list[str]) -> bool:
        tried.append(argv[0])
        return argv[0] != "/usr/bin/wslview"

    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: "/usr/bin/wslview")
    monkeypatch.setattr(browser, "_run", _run)
    assert browser.open_url(KITE) is True
    assert tried == ["/usr/bin/wslview", "powershell.exe"]


def test_off_wsl_it_is_just_the_normal_browser_module(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(browser, "is_wsl", lambda: False)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)
    assert browser.open_url(KITE) is True
    assert opened == [KITE]


# --- telling the truth ----------------------------------------------------------------------------
def test_it_returns_false_when_nothing_could_open_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The caller's whole job on this path is to say so and print the link."""
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    monkeypatch.setattr(browser.shutil, "which", lambda name: None)
    monkeypatch.setattr(browser, "_run", lambda argv: False)
    import webbrowser

    monkeypatch.setattr(webbrowser, "open", lambda u: False)
    assert browser.open_url(KITE) is False


def test_a_raising_webbrowser_is_a_false_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "is_wsl", lambda: False)
    import webbrowser

    def _boom(url: str) -> bool:
        raise RuntimeError("no display")

    monkeypatch.setattr(webbrowser, "open", _boom)
    assert browser.open_url(KITE) is False


def test_a_dead_helper_is_a_false_not_a_hang(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken interop layer must not block the app forever."""
    import subprocess

    def _timeout(*a: object, **k: object) -> object:
        raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=1)

    monkeypatch.setattr(browser.subprocess, "run", _timeout)
    assert browser._run(["powershell.exe"]) is False


def test_the_failure_message_carries_the_link_and_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browser, "is_wsl", lambda: True)
    message = browser.describe_failure(KITE)
    assert KITE in message
    assert "wslu" in message, "on WSL, say what would make it work next time"


def test_the_failure_message_off_wsl_does_not_mention_wsl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(browser, "is_wsl", lambda: False)
    message = browser.describe_failure(KITE)
    assert KITE in message
    assert "wslu" not in message

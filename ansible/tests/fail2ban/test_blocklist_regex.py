#!/usr/bin/env python3
r"""Regex tests for the Loki blocklist script.

The script is a Jinja template that shells out to Loki, so its patterns can only be
checked by extracting them and applying them to fixtures shaped like the real log lines.
Two escaping layers are in play and they are easy to confuse:

  * a Loki ``regexp "..."`` argument sits inside a shell **single**-quoted string, so the
    template text is exactly what Loki receives (Go RE2);
  * a jq ``test("^...$")`` argument is a jq string, so ``\\.`` in the template reaches jq
    as two characters, which jq unescapes to ``\.`` before compiling.

Nothing about Loki is mocked: the subject under test is the patterns.
"""

import re
import unittest
from pathlib import Path

TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "plays/roles/system/templates/fail2ban/update-blocklist-from-loki.sh.j2"
)

# Shapes taken from the deployed logs. Traefik's JSON carries the bare client host (no
# port) in ClientHost; sshd writes "from <host> port <n>".
TRAEFIK_V4 = '{"ClientAddr":"203.0.113.9:44321","ClientHost":"203.0.113.9","DownstreamStatus":404}'
TRAEFIK_V6 = '{"ClientAddr":"[2001:db8::42]:44321","ClientHost":"2001:db8::42","DownstreamStatus":404}'
AUTH_V4 = "servy sshd-session[1]: Invalid user x from 198.51.100.7 port 22 ssh2"
AUTH_V6 = "servy sshd-session[1]: Invalid user x from 2001:db8::13 port 22 ssh2"


def template_text():
    return TEMPLATE.read_text()


def loki_regexp_arguments(text):
    """Every ``regexp "..."`` argument, exactly as Loki receives it.

    The scan is manual because the argument may itself contain escaped quotes
    (``regexp "\\"ClientHost\\":\\"(?P<ip>[^\\"]+)\\""``).
    """
    out = []
    needle = 'regexp "'
    pos = 0
    while True:
        start = text.find(needle, pos)
        if start < 0:
            return out
        i = start + len(needle)
        buf = []
        while i < len(text):
            char = text[i]
            if char == "\\" and i + 1 < len(text):
                buf.append(text[i:i + 2])
                i += 2
                continue
            if char == '"':
                break
            buf.append(char)
            i += 1
        out.append("".join(buf))
        pos = i + 1


def jq_guard_patterns(text):
    """Every jq ``test("^...$")`` argument, unescaped and re-anchored the way jq sees it."""
    inner = [m.group(1).encode().decode("unicode_escape") for m in re.finditer(r'test\("\^([^"]+)\$"\)', text)]
    # The capture above strips the anchors; the guard is what jq compiles, so put them back.
    return [f"^{pattern}$" for pattern in inner]


class LokiPatternTest(unittest.TestCase):
    def setUp(self):
        self.arguments = loki_regexp_arguments(template_text())

    def test_arguments_are_found(self):
        # Guards the extraction itself: a rewrite that hides the patterns must fail
        # loudly rather than silently test nothing.
        self.assertGreaterEqual(len(self.arguments), 2, f"extracted {self.arguments!r}")
        for argument in self.arguments:
            self.assertIn("(?P<ip>", argument, f"no named ip group in {argument!r}")

    def test_every_argument_captures_v4_and_v6_hosts(self):
        for argument in self.arguments:
            rx = re.compile(argument)
            if "ClientHost" in argument:
                fixtures = ((TRAEFIK_V4, "203.0.113.9"), (TRAEFIK_V6, "2001:db8::42"))
            elif "from " in argument:
                fixtures = ((AUTH_V4, "198.51.100.7"), (AUTH_V6, "2001:db8::13"))
            else:  # pragma: no cover - add a fixture branch when a new shape appears
                self.fail(f"no fixture family for pattern {argument!r}")
            for line, expected in fixtures:
                with self.subTest(argument=argument, line=line):
                    match = rx.search(line)
                    self.assertIsNotNone(match, f"{argument!r} did not match {line!r}")
                    self.assertEqual(match.group("ip"), expected)

    def test_no_double_escaped_patterns(self):
        # `\\.` reaches Go RE2 as an escaped backslash, so it matches a literal backslash
        # followed by any character and extracts nothing. That shape is correct inside a
        # jq string, and it must not appear in a Loki pattern.
        for argument in self.arguments:
            with self.subTest(argument=argument):
                self.assertNotIn("\\\\", argument)

    def test_arguments_never_capture_a_port(self):
        for argument in self.arguments:
            rx = re.compile(argument)
            for line in (TRAEFIK_V4, TRAEFIK_V6, AUTH_V4, AUTH_V6):
                match = rx.search(line)
                if match is None:
                    continue
                with self.subTest(argument=argument, line=line):
                    self.assertFalse(
                        match.group("ip").endswith((":44321", " 44321")),
                        f"{argument!r} captured a port from {line!r}",
                    )


class JqGuardTest(unittest.TestCase):
    def setUp(self):
        self.patterns = jq_guard_patterns(template_text())

    def test_guards_are_found(self):
        self.assertGreaterEqual(len(self.patterns), 2, f"extracted {self.patterns!r}")

    def test_guards_accept_v4_and_v6_only(self):
        for pattern in self.patterns:
            rx = re.compile(pattern)
            with self.subTest(pattern=pattern):
                self.assertTrue(rx.search("203.0.113.9"), "v4 must pass")
                self.assertTrue(rx.search("2001:db8::42"), "v6 must pass")
                self.assertFalse(rx.search("203.0.113.9:44321"), "host:port must not pass")
                self.assertFalse(rx.search("2026-11-10T08:40:12"), "a timestamp must not pass")
                self.assertFalse(rx.search(""), "empty must not pass")


if __name__ == "__main__":
    unittest.main(verbosity=2)

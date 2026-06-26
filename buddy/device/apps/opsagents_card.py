"""OpsAgents Pocket Card — offline brand card for the Cardputer-Adv.

A four-page paginated card you scroll with the arrow keys. Tells the
OpsAgents story in four beats: who, what, how, why. No BLE, no
network — runs cleanly on event WiFi or fully offline. Designed to
sit alongside hello_cardputer, claude_buddy, snake in the App List
and feel like part of the same suite (same chrome, same exit
protocol, same keyboard rhythm).

### Why this exists

The Champion Kit story is "Anthropic-on-a-$50-device, flashed by
Claude Code in one command." A demo needs a card the audience can
read off the LCD — a tweetable summary that lives on the device
itself. Generic Claude Buddy + Snake demos exist; this is the *our*
app that turns a generic Cardputer into an OpsAgents Cardputer.

### Port notes

- **Screen.** 240x135 landscape. Same three-zone chrome as the rest
  of the bundle: 20 px DARK header + ORANGE hairline + body + hint
  strip. Consistency over ambition.

- **Pages.** Four cards, indexed 0..3, navigated with LEFT / RIGHT
  arrows or `,` / `.` on the QWERTY. A page indicator (●○○○) on
  the header line shows position. Wrap at the edges.

- **Keyboard.** MatrixKeyboard polled via `kb.tick()` + `kb.get_key()`
  at ~40 ms — same loop shape as the other apps.

- **Exit.** Q or ESC triggers `machine.reset()` in the `finally`
  block, dropping the user back at App List.

- **Font.** DejaVu9 size 1 for body / hints, size 2 for headlines.
  Centering uses `_LCD.textWidth(...)` because proportional widths
  defeat the naive `CHAR_W * len(text)` trick on this build.

- **Brand colors.** Inlined from the buddy bundle palette so the app
  visually belongs. The orange-on-dark theme is the upstream
  buddy/UIFlow vocabulary; OpsAgents' own purple lives on web, not
  here — fitting in is the right call for a single app in a shared
  launcher.
"""

import time

import M5
import machine
from hardware import MatrixKeyboard


# Inlined palette — keep in sync with hello_cardputer.py and
# claude_buddy.py if either changes.
_BLACK = 0x000000
_ORANGE = 0xCC785C
_CREAM = 0xF0EEE6
_DARK = 0x1F1F1F
_GRAY_MID = 0x777777

_LCD = M5.Lcd

_W = 240
_H = 135

# Four pages. Each is a (headline, [body lines]) tuple. Body lines
# render size-1 centered, max ~36 chars per line at this width.
_PAGES = (
    (
        "OpsAgents",
        (
            "Supervised  Orchestrated",
            "Secured  Agents",
            "",
            "opsagents.agency",
        ),
    ),
    (
        "What it is",
        (
            "Claude Code flashes this card",
            "in one command. ~3 min, no",
            "manuals. Code w/ Claude makers",
            "track, May 2026.",
        ),
    ),
    (
        "The stack",
        (
            "ESP32-S3  MicroPython",
            "Claude Buddy over BLE",
            "Cloud Run  Vertex  Trello",
            "All credit-covered.",
        ),
    ),
    (
        "Why this",
        (
            "A pocket-size Anthropic demo",
            "that flashes itself. Brand wedge,",
            "not a product. Repo:",
            "OpsAgentsAI/anthropic-adv",
        ),
    ),
)

# Tuned-for-row math: header is 0..20, hairline at 20, hint strip
# is _H-18.._H. The body lives in 24.._H-22.
_BODY_TOP = 28
_BODY_LINE_H = 14


def _set_font():
    try:
        _LCD.setFont(_LCD.FONTS.DejaVu9)
    except Exception as e:
        print("opsagents_card: setFont fallback:", e)


def _draw_chrome():
    """Background, header band, hairline, hint strip. Once at startup."""
    _LCD.fillScreen(_BLACK)
    _LCD.fillRect(0, 0, _W, 20, _DARK)
    _LCD.fillRect(0, 20, _W, 1, _ORANGE)
    _LCD.fillRect(0, _H - 18, _W, 18, _DARK)


def _draw_header(idx):
    """Refresh header row — title left, page indicator right."""
    _LCD.fillRect(0, 0, _W, 20, _DARK)
    _LCD.setTextSize(1)
    _LCD.setTextColor(_ORANGE, _DARK)
    _LCD.drawString("OpsAgents Pocket Card", 6, 5)
    # Page indicator: filled dot for current, hollow for others.
    # Render as glyphs because drawing actual circles costs more
    # code for negligible visual gain at this size.
    dots = "".join("●" if i == idx else "○" for i in range(len(_PAGES)))
    _LCD.setTextColor(_CREAM, _DARK)
    _LCD.drawString(dots, _W - 10 - _LCD.textWidth(dots), 5)


def _draw_hint(idx):
    """Hint strip — same content all pages, just refreshed on redraw."""
    _LCD.fillRect(0, _H - 18, _W, 18, _DARK)
    _LCD.setTextSize(1)
    _LCD.setTextColor(_GRAY_MID, _DARK)
    hint = "←/→  page   Q/ESC  back"
    _LCD.drawString(hint, (_W - _LCD.textWidth(hint)) // 2, _H - 14)


def _clear_body():
    _LCD.fillRect(0, 21, _W, _H - 21 - 18, _BLACK)


def _draw_page(idx):
    """Repaint the body region with the page at index idx."""
    _clear_body()
    headline, body_lines = _PAGES[idx]

    # Headline — size 2, centered, sits near the top of the body
    # region with a comfortable gap below the hairline.
    _LCD.setTextSize(2)
    _LCD.setTextColor(_ORANGE, _BLACK)
    _LCD.drawString(headline, (_W - _LCD.textWidth(headline)) // 2, _BODY_TOP)

    # Body lines — size 1, centered. Start far enough below the
    # headline (size-2 chars are 16 px tall) that there's air.
    _LCD.setTextSize(1)
    _LCD.setTextColor(_CREAM, _BLACK)
    y = _BODY_TOP + 22
    for line in body_lines:
        if line:
            _LCD.drawString(line, (_W - _LCD.textWidth(line)) // 2, y)
        y += _BODY_LINE_H


def _key_intent(k):
    """Map a key event to one of: 'left', 'right', 'exit', or None.

    The Cardputer-Adv keyboard returns ints (ASCII) for printables and
    a small set of special codes for arrows and ESC. We handle:
    - ESC (0x1B) or 'q'/'Q'   -> exit
    - LEFT ARROW (0xB4) or ',' -> left
    - RIGHT ARROW (0xB5) or '.' -> right
    """
    if k is None:
        return None

    # Normalize to int code for comparison.
    if isinstance(k, str) and k:
        code = ord(k[0])
    elif isinstance(k, int):
        code = k
    else:
        return None

    if code == 0x1B:
        return "exit"
    if code in (ord("q"), ord("Q")):
        return "exit"
    # MatrixKeyboard arrow codes on UIFlow 2.0 — values cross-checked
    # against snake.py which uses the same mapping. If a future
    # UIFlow bump changes these, adjust here and in snake.
    if code in (0xB4, ord(","), ord("<")):
        return "left"
    if code in (0xB5, ord("."), ord(">")):
        return "right"
    return None


def run():
    _set_font()
    _draw_chrome()

    idx = 0
    _draw_header(idx)
    _draw_page(idx)
    _draw_hint(idx)

    kb = MatrixKeyboard()
    # Same 400 ms debounce as the other apps so the launch keypress
    # doesn't immediately register as a page-flip.
    time.sleep_ms(400)

    try:
        while True:
            kb.tick()
            intent = _key_intent(kb.get_key())

            if intent == "exit":
                return

            if intent == "left":
                idx = (idx - 1) % len(_PAGES)
                _draw_header(idx)
                _draw_page(idx)
            elif intent == "right":
                idx = (idx + 1) % len(_PAGES)
                _draw_header(idx)
                _draw_page(idx)

            time.sleep_ms(40)
    finally:
        try:
            _LCD.fillScreen(_BLACK)
        except Exception as e:
            print("opsagents_card: clear warning:", e)
        time.sleep_ms(200)
        machine.reset()


run()

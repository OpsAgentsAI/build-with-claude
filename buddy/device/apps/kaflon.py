"""Kaflon — multiplication & division drill, on-device.

Pocket-sized math drill for the Cardputer-Adv. Sister to the web
version at https://kaflon.opsagents.agency · github.com/OpsAgentsAI/kaflon
— same game, ported to 240x135 LCD + QWERTY keyboard. Designed for
kids working through the x / ÷ tables up to 10x10.

### Why this exists

The web version is the community-OSS surface — fork it, share it,
ship it to your kid. *This* version is what Michal actually hands
her kid: a physical handheld, no notifications, no other tabs, no
"just one YouTube short." A device is a kinder learning surface
than a phone.

### Port notes

- **Screen.** 240x135 landscape. Same chrome as opsagents_card.py:
  20 px DARK header + ORANGE hairline + body + DARK hint strip.
  Consistency over ambition — kaflon should feel like part of the
  buddy suite, not a visual one-off.
- **States.** PICK -> PLAY -> RIGHT/WRONG -> PLAY (loop).
  ESC/Q triggers machine.reset() back to the launcher. M during
  play returns to mode-pick without exiting.
- **Modes.** 1=multiply, 2=divide, 3=mixed. Random across 1..10 in
  v0. Single-table drill is a v0.1 add on the Trello board.
- **Division.** Presented as (a*b) / b = a so answers are always
  whole numbers. Kids never see remainders in this drill.
- **Input.** Digit keys 0-9 append to the answer buffer (3-char
  cap, since 10x10=100). Backspace (0x08 or 0x7F) deletes. Enter
  (0x0D / 0x0A) submits. M re-picks mode. Q/ESC exits.
- **Feedback.** Correct -> green verdict, score++, streak++, any
  key -> next. Wrong -> red verdict, show correct answer + what
  the kid typed, streak=0, any key -> next. No auto-advance — the
  kid controls the pace.
- **Persistence.** None in v0. Score resets on exit. If the kid
  asks for it, v0.1 can persist best streak to /flash/data/kaflon.
- **Telemetry.** v0.1 adds structured `print()` lines to USB
  serial — one per question generated, one per answer submitted.
  Format is greppable from the host with `screen /dev/cu.usbmodem* 115200`
  or `pyserial`. Pattern analysis runs on the host side; the
  device just emits facts. Lines:
    KAFLON BOOT v=1
    KAFLON Q t=<ms> mode=<mul|div> q=<text> ans=<int>
    KAFLON A t=<ms> v=<right|wrong> typed=<int> correct=<int> dt=<ms> s=<int> k=<int>
  `t` = ticks_ms() at event. `dt` = elapsed_ms from question-shown
  to answer-submitted. `s` = score, `k` = streak after the event.
- **Font.** DejaVu9 size 1 for HUD/hints, size 2 for question
  and verdict. Same as opsagents_card.py — proportional widths
  defeat the naive CHAR_W*len(text) trick, so all centering goes
  through _LCD.textWidth().
"""

import random
import time

import M5
import machine
from hardware import MatrixKeyboard


# Palette — keep in sync with opsagents_card.py / hello_cardputer /
# claude_buddy so the app visually belongs.
_BLACK = 0x000000
_ORANGE = 0xCC785C
_CREAM = 0xF0EEE6
_DARK = 0x1F1F1F
_GRAY_MID = 0x777777
_GREEN = 0x4ADE80
_RED = 0xF87171

_LCD = M5.Lcd
_W = 240
_H = 135

_STATE_PICK = "pick"
_STATE_PLAY = "play"
_STATE_RIGHT = "right"
_STATE_WRONG = "wrong"

# Use ASCII operators in code; the on-screen labels can show
# Latin-1 supplement glyphs (DejaVu9 covers them — the buddy card
# already uses higher-codepoint geometric-shapes glyphs reliably).
_MODE_MUL = "mul"
_MODE_DIV = "div"
_MODE_MIX = "mix"

_OP_LABEL = {_MODE_MUL: "x", _MODE_DIV: "/", _MODE_MIX: "x/"}


def _set_font():
    try:
        _LCD.setFont(_LCD.FONTS.DejaVu9)
    except Exception as e:
        print("kaflon: setFont fallback:", e)


def _draw_chrome():
    """Background, header band, hairline, hint strip. Once at startup."""
    _LCD.fillScreen(_BLACK)
    _LCD.fillRect(0, 0, _W, 20, _DARK)
    _LCD.fillRect(0, 20, _W, 1, _ORANGE)
    _LCD.fillRect(0, _H - 18, _W, 18, _DARK)


def _draw_header(state, mode, score, streak):
    _LCD.fillRect(0, 0, _W, 20, _DARK)
    _LCD.setTextSize(1)
    if state == _STATE_PICK:
        _LCD.setTextColor(_ORANGE, _DARK)
        _LCD.drawString("Kaflon  pick a mode", 6, 5)
        return

    # Title left, score/streak right
    _LCD.setTextColor(_ORANGE, _DARK)
    title = "Kaflon  " + _OP_LABEL.get(mode, "?")
    _LCD.drawString(title, 6, 5)

    _LCD.setTextColor(_CREAM, _DARK)
    right = "S:" + str(score) + "  +" + str(streak)
    _LCD.drawString(right, _W - 6 - _LCD.textWidth(right), 5)


def _draw_hint(text):
    _LCD.fillRect(0, _H - 18, _W, 18, _DARK)
    _LCD.setTextSize(1)
    _LCD.setTextColor(_GRAY_MID, _DARK)
    _LCD.drawString(text, (_W - _LCD.textWidth(text)) // 2, _H - 14)


def _clear_body():
    _LCD.fillRect(0, 21, _W, _H - 21 - 18, _BLACK)


def _draw_pick_body():
    _clear_body()
    _LCD.setTextSize(2)
    _LCD.setTextColor(_ORANGE, _BLACK)
    title = "Pick a mode"
    _LCD.drawString(title, (_W - _LCD.textWidth(title)) // 2, 28)

    _LCD.setTextSize(1)
    _LCD.setTextColor(_CREAM, _BLACK)
    options = (
        "1   Multiply   (x)",
        "2   Divide     (/)",
        "3   Mixed      (x /)",
    )
    y = 62
    for line in options:
        _LCD.drawString(line, (_W - _LCD.textWidth(line)) // 2, y)
        y += 14


def _draw_question(q, answer_buf):
    _clear_body()
    _LCD.setTextSize(2)
    _LCD.setTextColor(_ORANGE, _BLACK)
    _LCD.drawString(q, (_W - _LCD.textWidth(q)) // 2, 32)

    shown = answer_buf if answer_buf else "_"
    _LCD.setTextSize(2)
    _LCD.setTextColor(_CREAM, _BLACK)
    _LCD.drawString(shown, (_W - _LCD.textWidth(shown)) // 2, 72)


def _draw_feedback(state, q, correct_answer, user_answer):
    color = _GREEN if state == _STATE_RIGHT else _RED
    verdict = "Correct!" if state == _STATE_RIGHT else "Try again"
    _clear_body()

    _LCD.setTextSize(1)
    _LCD.setTextColor(_GRAY_MID, _BLACK)
    eq = q + " = " + str(correct_answer)
    _LCD.drawString(eq, (_W - _LCD.textWidth(eq)) // 2, 28)

    _LCD.setTextSize(2)
    _LCD.setTextColor(color, _BLACK)
    _LCD.drawString(verdict, (_W - _LCD.textWidth(verdict)) // 2, 50)

    if state == _STATE_WRONG:
        _LCD.setTextSize(1)
        _LCD.setTextColor(_CREAM, _BLACK)
        you = "you said " + str(user_answer)
        _LCD.drawString(you, (_W - _LCD.textWidth(you)) // 2, 82)


def _new_question(mode):
    """Return (question_text, correct_answer, op_label)."""
    if mode == _MODE_MIX:
        op = _MODE_MUL if random.random() < 0.5 else _MODE_DIV
    else:
        op = mode

    a = random.randint(1, 10)
    b = random.randint(1, 10)

    if op == _MODE_MUL:
        return ("{} x {}".format(a, b), a * b, "mul")
    # Division: (a*b) / b = a so the answer is always whole.
    return ("{} / {}".format(a * b, b), a, "div")


def _key_code(k):
    """Normalize a kb.get_key() return value to an int code or None."""
    if k is None:
        return None
    if isinstance(k, str) and k:
        return ord(k[0])
    if isinstance(k, int):
        return k
    return None


def _enter_pick(score, streak):
    _draw_header(_STATE_PICK, None, score, streak)
    _draw_pick_body()
    _draw_hint("1/2/3  pick   Q/ESC  back")


def _enter_play(mode, score, streak, q, answer_buf):
    _draw_header(_STATE_PLAY, mode, score, streak)
    _draw_question(q, answer_buf)
    _draw_hint("0-9  type   Enter  check   M  mode   Q  back")


def _enter_feedback(state, mode, score, streak, q, correct, user_v):
    _draw_header(state, mode, score, streak)
    _draw_feedback(state, q, correct, user_v)
    _draw_hint("any key  next   Q  back")


def run():
    _set_font()
    _draw_chrome()

    print("KAFLON BOOT v=1")

    state = _STATE_PICK
    mode = None
    score = 0
    streak = 0
    answer_buf = ""
    current_q = ""
    current_ans = 0
    current_op = ""
    q_shown_ms = 0
    user_v = 0

    _enter_pick(score, streak)

    kb = MatrixKeyboard()
    # Same 400 ms debounce as the other apps so the keypress that
    # launched us from the App List doesn't pre-pick mode 1.
    time.sleep_ms(400)

    try:
        while True:
            kb.tick()
            code = _key_code(kb.get_key())

            if code is not None:
                # Global exit — works from any state.
                if code == 0x1B or code in (ord("q"), ord("Q")):
                    return

                if state == _STATE_PICK:
                    picked = None
                    if code == ord("1"):
                        picked = _MODE_MUL
                    elif code == ord("2"):
                        picked = _MODE_DIV
                    elif code == ord("3"):
                        picked = _MODE_MIX
                    if picked is not None:
                        mode = picked
                        current_q, current_ans, current_op = _new_question(mode)
                        q_shown_ms = time.ticks_ms()
                        print("KAFLON Q t={} mode={} q={} ans={}".format(
                            q_shown_ms, current_op, current_q, current_ans))
                        answer_buf = ""
                        state = _STATE_PLAY
                        _enter_play(mode, score, streak, current_q, answer_buf)

                elif state == _STATE_PLAY:
                    if code in (ord("m"), ord("M")):
                        state = _STATE_PICK
                        mode = None
                        _enter_pick(score, streak)
                    elif ord("0") <= code <= ord("9"):
                        if len(answer_buf) < 3:
                            answer_buf += chr(code)
                            _draw_question(current_q, answer_buf)
                    elif code in (0x08, 0x7F):
                        if answer_buf:
                            answer_buf = answer_buf[:-1]
                            _draw_question(current_q, answer_buf)
                    elif code in (0x0D, 0x0A):
                        if not answer_buf:
                            continue
                        try:
                            user_v = int(answer_buf)
                        except ValueError:
                            continue
                        now_ms = time.ticks_ms()
                        dt = time.ticks_diff(now_ms, q_shown_ms)
                        if user_v == current_ans:
                            score += 1
                            streak += 1
                            state = _STATE_RIGHT
                            verdict = "right"
                        else:
                            streak = 0
                            state = _STATE_WRONG
                            verdict = "wrong"
                        print("KAFLON A t={} v={} typed={} correct={} dt={} s={} k={} q={}".format(
                            now_ms, verdict, user_v, current_ans, dt, score, streak, current_q))
                        _enter_feedback(state, mode, score, streak,
                                        current_q, current_ans, user_v)

                elif state in (_STATE_RIGHT, _STATE_WRONG):
                    # Any key (other than Q/ESC handled above) advances.
                    current_q, current_ans, current_op = _new_question(mode)
                    q_shown_ms = time.ticks_ms()
                    print("KAFLON Q t={} mode={} q={} ans={}".format(
                        q_shown_ms, current_op, current_q, current_ans))
                    answer_buf = ""
                    state = _STATE_PLAY
                    _enter_play(mode, score, streak, current_q, answer_buf)

            time.sleep_ms(40)
    finally:
        try:
            _LCD.fillScreen(_BLACK)
        except Exception as e:
            print("kaflon: clear warning:", e)
        time.sleep_ms(200)
        machine.reset()


run()

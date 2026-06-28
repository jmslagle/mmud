from mmud.automation.login import LoginHandler
from mmud.config.schema import LoginConfig


def test_matches_username_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Enter your username:")
    assert cmd == "spawn"


def test_matches_password_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    handler.process_line("Enter your username:")  # advance state
    cmd = handler.process_line("Enter your password:")
    assert cmd == "hunter2"


def test_matches_character_select():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Select your character (Spawn DaPrawn):")
    assert cmd is not None
    assert "Spawn DaPrawn" in cmd or cmd.isdigit() or cmd.lower() == "spawn daprawn"


def test_majormud_menu_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Welcome to MAJORMUD - Press any key to continue")
    assert cmd is not None  # sends enter or game command


def test_game_full_detected():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    assert handler.game_full is False
    handler.process_line("The game is currently full. Please try again later.")
    assert handler.game_full is True


def test_game_entered_detected():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    assert handler.in_game is False
    handler.process_line("Your character has been saved.")
    assert handler.in_game is True


def test_no_match_returns_none():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn", auto_login=True)
    handler = LoginHandler(cfg)
    assert handler.process_line("You notice 3 orcs here.") is None
    assert handler.process_line("Obvious exits: north") is None


def test_blank_config_skips_login():
    """With no username configured, handler returns None for all prompts."""
    handler = LoginHandler(LoginConfig())
    assert handler.process_line("Enter your username:") is None


def test_matches_worldgroup_userid_prompt():
    # Galacticomm Worldgroup (hosts MajorMud) — User-ID cue is mid-line.
    cfg = LoginConfig(username="Raist", password="test12", auto_login=True)
    h = LoginHandler(cfg)
    line = ('If you already have a User-ID on this system, type it in and '
            'press ENTER.  Otherwise type "new":')
    assert h.process_line(line) == "Raist"


def test_worldgroup_password_then_username_sequence():
    cfg = LoginConfig(username="Raist", password="test12", auto_login=True)
    h = LoginHandler(cfg)
    assert h.process_line('...have a User-ID...type "new":') == "Raist"
    assert h.process_line("Password:") == "test12"


def test_custom_prompt_override():
    cfg = LoginConfig(username="Raist", password="pw", auto_login=True,
                      username_prompt=r"gimme your name")
    h = LoginHandler(cfg)
    assert h.process_line("Enter your username:") is None   # default cue ignored
    assert h.process_line("Please gimme your name now") == "Raist"


def test_worldgroup_nonstop_prompt():
    # MegaMud answers the pager with a bare Enter (Continue), never "Q".
    cfg = LoginConfig(username="Raist", password="pw", auto_login=True)
    h = LoginHandler(cfg)
    assert h.process_line("(N)onstop, (Q)uit, or (C)ontinue?") == ""


def test_generic_pager_prompt_presses_enter():
    cfg = LoginConfig(username="Raist", password="pw", auto_login=True)
    h = LoginHandler(cfg)
    assert h.process_line("Press [ENTER] to continue") == ""
    assert h.process_line("More [Y,n,=]?") == ""


# ---- scripted login (MegaMud-style LogonPrompt/LogonReply) ------------------

def _scripted_cfg(**kw):
    from mmud.config.schema import LoginConfig, LoginStep
    # Note: the (N)onstop pager and "[MAJORMUD]:" entry are NOT scripted — MegaMud handles
    # them automatically (see the always-on tests below). The script carries only the
    # genuinely BBS-specific prompts.
    return LoginConfig(
        username="Raist", password="test12", character="Raistlin",
        auto_login=True,
        script=[
            LoginStep(prompt=r"User-ID|type it in and press", reply="{userid}"),
            LoginStep(prompt=r"[Pp]assword", reply="{pswd}"),
            LoginStep(prompt=r"Enter your selection", reply="D"),
        ],
        menu_prompt=r"Already playing",
        **kw,
    )


def test_scripted_login_runs_steps_in_order_with_expansion():
    h = LoginHandler(_scripted_cfg())
    # unrelated lines are ignored until the current step's prompt appears
    assert h.process_line("Welcome to MorningSide Mortuary") is None
    assert h.process_line('...have a User-ID...type "new":') == "Raist"
    assert h.process_line("Password:") == "test12"
    # a (N)onstop pager mid-sequence is auto-handled (Enter) and does NOT consume a step
    assert h.process_line("(N)onstop, (Q)uit, or (C)ontinue?") == ""
    assert h.process_line("(N)onstop, (Q)uit, or (C)ontinue?") == ""   # however many appear
    assert h.process_line("Enter your selection:") == "D"              # next step still pending
    # script exhausted -> no further replies (but the pager stays auto-handled)
    assert h.process_line("anything else") is None
    assert h.process_line("Press any key to continue") == ""


def test_scripted_login_is_strictly_sequential():
    h = LoginHandler(_scripted_cfg())
    # a later (non-pager) step's prompt seen early does NOT fire before its turn
    assert h.process_line("Enter your selection:") is None
    assert h.process_line('User-ID: type "new":') == "Raist"


def test_menu_prompt_marks_in_game():
    h = LoginHandler(_scripted_cfg())
    assert h.in_game is False
    h.process_line("You are Already playing this character")   # reconnect cue
    assert h.in_game is True


def test_nonstop_pager_auto_handled_even_with_a_script():
    # The bug: with a script configured, the pager used to be ignored (or wrongly scripted
    # to "Q", which quits). It must be auto-answered with Enter regardless of the script,
    # and work for MULTIPLE pagers (count varies with the who-list/news length).
    h = LoginHandler(_scripted_cfg())
    for _ in range(5):
        assert h.process_line("(N)onstop, (Q)uit, or (C)ontinue?") == ""


def test_majormud_prompt_enters_the_realm():
    # "[MAJORMUD]:" menu -> send "enter" to enter the game (MegaMud s_enter_004be16c).
    h = LoginHandler(_scripted_cfg())
    assert h.process_line("[MAJORMUD]:") == "enter"


def test_hp_prompt_marks_in_game():
    # The authoritative MegaMud in-game signal is a "[HP=...]:" prompt at line start.
    h = LoginHandler(_scripted_cfg())
    assert h.in_game is False
    assert h.process_line("[HP=168/MA=72]:") is None
    assert h.in_game is True


def test_scripted_login_resets_for_relog():
    h = LoginHandler(_scripted_cfg())
    assert h.process_line('User-ID type "new":') == "Raist"
    h.reset()
    assert h.process_line('User-ID type "new":') == "Raist"   # step 0 again


def test_no_script_falls_back_to_builtin_detection():
    cfg = LoginConfig(username="spawn", password="pw", auto_login=True)  # no script
    h = LoginHandler(cfg)
    assert h.process_line("Enter your username:") == "spawn"

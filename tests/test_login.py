from mmud.automation.login import LoginHandler
from mmud.config.schema import LoginConfig


def test_matches_username_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Enter your username:")
    assert cmd == "spawn"


def test_matches_password_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    handler.process_line("Enter your username:")  # advance state
    cmd = handler.process_line("Enter your password:")
    assert cmd == "hunter2"


def test_matches_character_select():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Select your character (Spawn DaPrawn):")
    assert cmd is not None
    assert "Spawn DaPrawn" in cmd or cmd.isdigit() or cmd.lower() == "spawn daprawn"


def test_majormud_menu_prompt():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    cmd = handler.process_line("Welcome to MAJORMUD - Press any key to continue")
    assert cmd is not None  # sends enter or game command


def test_game_full_detected():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    assert handler.game_full is False
    handler.process_line("The game is currently full. Please try again later.")
    assert handler.game_full is True


def test_game_entered_detected():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    assert handler.in_game is False
    handler.process_line("Your character has been saved.")
    assert handler.in_game is True


def test_no_match_returns_none():
    cfg = LoginConfig(username="spawn", password="hunter2", character="Spawn DaPrawn")
    handler = LoginHandler(cfg)
    assert handler.process_line("You notice 3 orcs here.") is None
    assert handler.process_line("Obvious exits: north") is None


def test_blank_config_skips_login():
    """With no username configured, handler returns None for all prompts."""
    handler = LoginHandler(LoginConfig())
    assert handler.process_line("Enter your username:") is None

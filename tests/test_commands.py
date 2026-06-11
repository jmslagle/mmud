from mmud.commands import expand_template


def test_plain_passthrough():
    assert expand_template("kill orc") == "kill orc"


def test_tokens():
    out = expand_template("tell {target} hi from {userid}",
                          {"target": "orc", "userid": "Bee"})
    assert out == "tell orc hi from Bee"


def test_unknown_token_empty():
    assert expand_template("hi {nosuch} there") == "hi  there"


def test_alternatives_choose_injected():
    t = "say one||say two||say three"
    assert expand_template(t, choose=lambda n: 0) == "say one"
    assert expand_template(t, choose=lambda n: 2) == "say three"


def test_control_escapes():
    assert expand_template("hi^M") == "hi\r"
    assert expand_template("a^^b") == "a^b"
    assert expand_template("a^~b") == "a~b"


def test_tilde_is_ansi_leadin():
    assert expand_template("~[1m") == "\x01[1m"


def test_dmg_and_captures():
    out = expand_template("{dmg} {p1} {p5}", {"dmg": "42", "p1": "x"})
    assert out == "42 x "

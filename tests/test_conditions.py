from mmud.state.conditions import Condition, scan_onset, scan_recovery


def test_poison_onset():
    assert scan_onset("You have been poisoned!") is Condition.POISONED


def test_blind_onset():
    assert scan_onset("You are blind!") is Condition.BLIND
    assert scan_onset("You cannot see a thing!") is Condition.BLIND


def test_held_onset():
    assert scan_onset("You have been paralyzed!") is Condition.HELD
    assert scan_onset("You cannot move!") is Condition.HELD


def test_disease_onset():
    assert scan_onset("You feel very ill.") is Condition.DISEASED


def test_normal_line_is_not_a_condition():
    assert scan_onset("You notice 2 orcs here.") is None
    assert scan_onset("[HP=100/100]:") is None
    assert scan_onset("") is None


def test_poison_recovery():
    assert scan_recovery("The poison has worn off.") is Condition.POISONED


def test_blind_recovery():
    assert scan_recovery("You can see again!") is Condition.BLIND


def test_recovery_does_not_match_onset_lines():
    assert scan_recovery("You have been poisoned!") is None

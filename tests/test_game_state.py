from mmud.state.game_state import GameState, Effect
from mmud.data.messages import MessagePattern
from mmud.parser.matcher import MatchResult


def _make_result(name, flags, is_apply, captures=None):
    p = MessagePattern(name=name, flags=flags, third_field=0,
                       apply_message="x", remove_message="y")
    return MatchResult(pattern=p, is_apply=is_apply, captures=captures or {})


def test_initial_state():
    gs = GameState()
    assert gs.current_room == ""
    assert gs.hp == 0
    assert gs.max_hp == 0
    assert gs.mana == 0
    assert gs.active_effects == set()


def test_apply_effect():
    gs = GameState()
    gs.apply_match(_make_result("chain", 0x10, is_apply=True))
    assert "chain" in gs.active_effects


def test_remove_effect():
    gs = GameState()
    gs.apply_match(_make_result("chain", 0x10, is_apply=True))
    gs.apply_match(_make_result("chain", 0x10, is_apply=False))
    assert "chain" not in gs.active_effects


def test_hp_update():
    gs = GameState()
    gs.set_hp(80, 100)
    assert gs.hp == 80
    assert gs.max_hp == 100


def test_room_update():
    gs = GameState()
    gs.set_room("HOME")
    assert gs.current_room == "HOME"


def test_command_queue():
    gs = GameState()
    gs.enqueue("n")
    gs.enqueue("e")
    assert gs.dequeue() == "n"
    assert gs.dequeue() == "e"
    assert gs.dequeue() is None


def test_combat_stats_hit():
    gs = GameState()
    gs.record_hit(damage=25)
    assert gs.combat_hits == 1
    assert gs.avg_damage == 25.0


def test_combat_stats_hit_pct():
    gs = GameState()
    gs.record_hit(10)
    gs.record_hit(20)
    gs.record_miss()
    assert abs(gs.hit_pct - 66.67) < 0.1


def test_combat_stats_reset():
    gs = GameState()
    gs.record_hit(50)
    gs.record_miss()
    gs.reset_combat_stats()
    assert gs.combat_hits == 0
    assert gs.combat_misses == 0


from mmud.state.tasks import TaskType


def test_game_state_starts_idle():
    gs = GameState()
    assert not gs.task.is_active


def test_begin_and_complete_task():
    gs = GameState()
    gs.begin_task(TaskType.RESTING, priority=50, timeout_s=30.0, now=100.0)
    assert gs.task.is_active
    assert gs.task.type is TaskType.RESTING
    assert gs.task.priority == 50
    assert gs.task.deadline == 130.0
    gs.complete_task()
    assert not gs.task.is_active


def test_begin_task_without_timeout_has_no_deadline():
    gs = GameState()
    gs.begin_task(TaskType.CASTING, priority=10, now=100.0)
    assert gs.task.deadline == 0.0


def test_abort_task():
    gs = GameState()
    gs.begin_task(TaskType.CASTING, priority=10, payload={"condition": "BLIND"})
    assert gs.task.payload == {"condition": "BLIND"}
    gs.abort_task()
    assert not gs.task.is_active
    assert gs.task.payload == {}


from mmud.state.game_state import MonsterSighting


def test_sightings_and_names():
    gs = GameState()
    gs.monsters_present.append(MonsterSighting(name="orc", count=2, exp_each=100))
    gs.monsters_present.append(MonsterSighting(name="rat", count=1, exp_each=20))
    assert gs.monster_names() == ["orc", "rat"]
    assert gs.monster_count() == 3
    assert gs.monster_exp_total() == 220

from mmud.state.tasks import TaskType, TaskState


def test_default_task_is_idle():
    t = TaskState()
    assert t.type is TaskType.IDLE
    assert not t.is_active


def test_active_task():
    t = TaskState(type=TaskType.RESTING, priority=50)
    assert t.is_active


def test_expired_with_deadline():
    t = TaskState(type=TaskType.RESTING, priority=50, deadline=100.0)
    assert not t.expired(now=99.0)
    assert t.expired(now=100.0)


def test_no_deadline_never_expires():
    t = TaskState(type=TaskType.RESTING, priority=50)
    assert not t.expired(now=1e9)


def test_idle_task_never_expires():
    t = TaskState(deadline=1.0)
    assert not t.expired(now=100.0)


def test_all_original_task_types_exist():
    # The 13 task names from megamud.exe's task state machine
    for name in ("GETTING", "DROPPING", "STASHING", "EQUIPPING", "SEARCHING",
                 "RUNNING", "BLESSING", "CASTING", "RESTING", "WAITING",
                 "RELOGGING", "HANGING", "TRAINING"):
        assert hasattr(TaskType, name)

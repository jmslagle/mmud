"""Replay of the real broken session (logs/session.log, Newhaven Arena fight)
through the bot pipeline, asserting the parsing fixes hold end-to-end."""
import pytest
from conftest import make_transcript_bot


async def _feed(bot, *lines):
    for line in lines:
        await bot._process_line(line)


@pytest.mark.asyncio
async def test_arena_fight_roster_and_exp():
    bot = make_transcript_bot([])

    # Enter the Arena: two monsters listed.
    await _feed(
        bot,
        "Newhaven, Arena",
        "Also here: angry kobold thief, kobold thief.",
        "Obvious exits: open door north, up",
    )
    assert bot._state.monster_names() == ["angry kobold thief", "kobold thief"]

    # Combat engages (authoritative marker).
    await _feed(bot, "*Combat Engaged*")
    assert bot._state.in_combat is True

    # *Combat Off* fires between rounds — roster must be preserved.
    await _feed(bot, "*Combat Off*", "*Combat Engaged*")
    assert bot._state.monster_names() == ["angry kobold thief", "kobold thief"]

    # A kill: "You gain N experience" counts the kill, accrues exp, and drops the
    # current target (the first/priority monster).
    await _feed(
        bot,
        "You fire a magic missile at angry kobold thief for 12 damage!",
        "The kobold thief falls to the ground with a shrill cry.",
        "You gain 26 experience.",
    )
    assert bot._session.exp_gained == 26
    assert bot._state.kills == 1
    # "kobold thief" removed by the named-death line; target removed by the kill.
    assert "kobold thief" not in [m.lower() for m in bot._state.monster_names()]

    # Room re-display with only one monster -> roster REPLACED (no accumulation).
    await _feed(
        bot,
        "Newhaven, Arena",
        "Also here: kobold thief.",
        "Obvious exits: open door north, up",
    )
    assert bot._state.monster_names() == ["kobold thief"]


@pytest.mark.asyncio
async def test_do_not_see_drops_phantom_target():
    bot = make_transcript_bot([])
    await _feed(
        bot,
        "Also here: angry kobold thief, kobold thief.",
        "Obvious exits: north",
    )
    # Server rejects a stale target -> it must be dropped (no infinite re-cast).
    await _feed(bot, "You do not see angry kobold thief here!")
    assert bot._state.monster_names() == ["kobold thief"]


@pytest.mark.asyncio
async def test_no_bare_kill_after_monster_dies_while_in_combat():
    # Regression: after a kill the in_combat flag lingers a beat before *Combat
    # Off*; with the roster empty the bot must NOT emit a bare "kill" (the log
    # showed "TX kill" -> server `You say "kill"`).
    bot = make_transcript_bot([])
    await _feed(bot, "Also here: kobold thief.", "Obvious exits: north",
                "*Combat Engaged*")
    assert bot._state.in_combat is True
    await _feed(
        bot,
        "The kobold thief falls to the ground with a shrill cry.",
        "You gain 26 experience.",
    )
    # Monster gone but combat flag may still be set -> no targetless attack.
    assert bot._state.monster_names() == []
    assert bot._next_command() is None


@pytest.mark.asyncio
async def test_player_spy_replay(tmp_path):
    # Replay the Horis sequence: room sighting -> examine -> looking-at, and
    # confirm the player is learned/persisted and session counters update.
    from mmud.config.schema import MudConfig, LearningConfig
    cfg = MudConfig()
    cfg.learning = LearningConfig(enabled=True, store_path=str(tmp_path / "db.json"))
    bot = make_transcript_bot([], config=cfg, data_dir=None)
    await _feed(
        bot,
        "Also here: Horis, giant rat.",
        "Obvious exits: north",
        "[ Horis ]",
        "Horis is a solid, well built Dark-Elf Gypsy with no hair and black eyes.  He",
        "Horis is looking at you.",
    )
    assert "Horis" in bot._state.players_present
    assert bot._state.monster_names() == ["giant rat"]   # player not a monster
    assert bot._session.people_seen == 1
    assert bot._session.attacked == 1
    learned = bot._store.players()["horis"]
    assert learned["race"] == "Dark-Elf" and learned["class"] == "Gypsy"
    # Persisted: a fresh store from the same path round-trips the record.
    from mmud.data.store import GameStore
    import pathlib
    assert GameStore(pathlib.Path(cfg.learning.store_path)).players()["horis"]["class"] == "Gypsy"


@pytest.mark.asyncio
async def test_wrapped_also_here_is_stitched():
    # Regression: the server word-wraps a long monster list across two lines
    # ("...nasty\ngiant rat."). Both must be stitched so all 5 monsters parse,
    # else the bot sees no monsters and walks through the room (combat misses).
    bot = make_transcript_bot([])
    await _feed(
        bot,
        "Newhaven, Arena 2",
        "Also here: cave worm, nasty kobold thief, acid slime, fat giant rat, nasty",
        "giant rat.",
        "Obvious exits: down",
    )
    assert bot._state.monster_names() == [
        "cave worm", "nasty kobold thief", "acid slime",
        "fat giant rat", "nasty giant rat",
    ]


@pytest.mark.asyncio
async def test_empty_room_clears_stale_monsters():
    bot = make_transcript_bot([])
    await _feed(bot, "Also here: kobold thief.", "Obvious exits: north")
    assert bot._state.monster_names() == ["kobold thief"]
    # Move to a monster-free room (no "Also here:") -> roster cleared at exits.
    await _feed(
        bot,
        "Newhaven, Narrow Road",
        "This narrow road is quite plain.",
        "Obvious exits: north, east, west, down",
    )
    assert bot._state.monster_names() == []

from __future__ import annotations
import time
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from mmud.bot import MudBot

# verb handler signature: (sender, arg) -> reply text
VerbHandler = Callable[[str, str], str]


class RemoteCommandHandler:
    """Telepath-command dispatcher, after megamud.exe's say_tell_message_dispatch.

    Verbs are a registry so later phases can add their own
    (@wealth → Phase 5, @relog → Phase 9, @invite/@wait → Phase 10).
    Permission: sender must match a PlayerRule whose remote_cmds contains
    the verb or "*". Unknown senders are denied silently (no reply leak).
    """

    def __init__(self, bot: "MudBot") -> None:
        self._bot = bot
        self._verbs: dict[str, VerbHandler] = {}
        self._register_builtins()

    def register(self, verb: str, handler: VerbHandler) -> None:
        self._verbs[verb.lower()] = handler

    def handle(self, sender: str, text: str) -> str | None:
        """Process a tell. Returns reply text, or None for no reply."""
        text = text.strip()
        if not text.startswith("@"):
            return None
        parts = text[1:].split(None, 1)
        verb = parts[0].lower() if parts else ""
        arg = parts[1].strip() if len(parts) > 1 else ""
        if verb not in self._verbs:
            return None
        rule = self._find_rule(sender)
        if rule is None:
            return None   # unknown player: silent
        if "*" not in rule.remote_cmds and verb not in rule.remote_cmds:
            return "permission denied"
        return self._verbs[verb](sender, arg)

    def _find_rule(self, sender: str):
        for rule in self._bot._config.players:
            if rule.name.lower() == sender.lower():
                return rule
        return None

    # ---- built-in verbs ----------------------------------------------------

    def _register_builtins(self) -> None:
        bot = self._bot
        self.register("status", lambda s, a: bot.status_text())
        self.register("health", lambda s, a: (
            f"HP {bot._state.hp}/{bot._state.max_hp} "
            f"MP {bot._state.mana}/{bot._state.max_mana}"
        ))
        self.register("loop", lambda s, a: bot.start_loop(a))
        self.register("stop", lambda s, a: bot.stop_all())
        self.register("db", self._db_stats)
        self.register("events", lambda s, a: (
            ", ".join(f"{desc} in {int(secs)}s"
                      for desc, secs in bot._scheduler.pending(time.monotonic()))
            or "no events scheduled"
        ))
        self.register("relog", self._relog)
        self.register("rate", lambda s, a: (
            f"exp rate {bot._session.exp_rate_per_hour():.0f}/hr "
            f"({bot._session.hours_elapsed(time.monotonic()):.1f}h session)"
        ))
        self.register("wealth", lambda s, a: (
            f"wealth {bot._state.inventory.wealth_total()} copper-equiv "
            f"({', '.join(f'{n} {d}' for d, n in bot._state.inventory.coins.items()) or 'no coins'})"
        ))
        self.register("goto", lambda s, a: bot.navigate_to_room(a) if a else "usage: @goto CODE")
        self.register("invite", lambda s, a: (
            bot._state.enqueue(f"invite {s}") or f"inviting {s}"))
        self.register("wait", lambda s, a: (
            bot._state.enqueue(bot._config.party.wait_cmd) or "waiting"))
        self.register("rego", lambda s, a: (
            bot._state.enqueue(bot._config.party.resume_cmd) or "resuming"))
        self.register("share", lambda s, a: (
            bot._state.enqueue(f"share {a}".strip()) or "sharing"))
        self.register("forget", self._forget_party)
        self.register("kill", self._kill)
        self.register("hangup", self._hangup)
        self.register("panic!", self._panic)
        # Toggle existing config flags, after the original's @auto-* verbs
        self.register("auto-sneak", self._toggle("stealth", "auto_sneak"))
        self.register("auto-hide", self._toggle("stealth", "auto_hide"))
        self.register("auto-get", self._toggle("items", "auto_get"))
        self.register("auto-cash", self._toggle("items", "auto_cash"))

    def _kill(self, sender: str, arg: str) -> str:
        if not arg:
            return "usage: @kill TARGET"
        self._bot._state.enqueue(f"{self._bot._config.combat.attack_cmd} {arg}")
        return f"attacking {arg}"

    def _relog(self, sender: str, arg: str) -> str:
        self._bot.request_relog(f"remote @relog from {sender}")
        return "relogging"

    def _forget_party(self, sender: str, arg: str) -> str:
        self._bot._state.party = []
        self._bot._state.party_leader = ""
        return "party forgotten"

    def _db_stats(self, sender: str, arg: str) -> str:
        store = getattr(self._bot, "_store", None)
        if store is None:
            return "learning disabled"
        d = store.data
        return (f"{len(d['monsters'])} monsters, {len(d['items'])} items, "
                f"{len(d['spells'])} spells, {len(d['exits'])} learned exits, "
                f"{len(d['collisions'])} collisions")

    def _hangup(self, sender: str, arg: str) -> str:
        self._bot._safety.request_hangup(f"remote @hangup from {sender}")
        return "hanging up"

    def _panic(self, sender: str, arg: str) -> str:
        panic_cmd = self._bot._config.safety.panic_cmd
        if panic_cmd:
            self._bot._state.enqueue(panic_cmd)
        self._bot._safety.request_hangup(f"remote @panic from {sender}")
        return "panic!"

    def _toggle(self, section: str, attr: str) -> VerbHandler:
        def toggle(sender: str, arg: str) -> str:
            svc = self._bot._config_service
            if arg:
                value = arg.strip().lower() in ("on", "true", "1", "yes")
            else:
                value = not getattr(getattr(svc.config, section), attr)
            svc.patch(section, attr, value)
            return f"{attr} {'on' if value else 'off'}"
        return toggle

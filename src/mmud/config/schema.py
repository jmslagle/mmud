from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 4000


@dataclass
class LoginConfig:
    username: str = ""
    password: str = ""
    character: str = ""
    auto_login: bool = False   # must be explicitly true to enable auto-login


@dataclass
class CombatConfig:
    attack_cmd: str = "kill"
    flee_threshold: float = 0.15
    rest_threshold: float = 0.40
    backstab: bool = False
    polite_attacks: bool = False
    attack_order: str = "first"   # "first" | "last" | "reverse"
    mana_attack_pct: float = 0.20
    max_monsters: int = 0          # run if more monsters than this (0 = no limit)
    max_monster_exp: int = 0       # run if summed exp exceeds this (0 = no limit)
    run_backwards: bool = False    # retrace recent moves instead of 'flee'
    run_if_bs_fails: bool = False  # run away when a backstab attempt fails
    monster_priority: list[str] = field(default_factory=list)  # attack these first


@dataclass
class BlessSpell:
    cmd: str = ""
    mana_pct: float = 0.80


@dataclass
class SpellsConfig:
    attack: str = ""
    pre_attack: str = ""
    multi_attack: str = ""
    heal: str = ""
    heal_hp_pct: float = 0.50
    mana_heal: str = ""
    mana_heal_pct: float = 0.30
    bless: list[BlessSpell] = field(default_factory=list)
    max_cast_count: int = 0        # attack-spell casts per encounter (0 = unlimited)
    cast_weapon_cmd: str = ""      # full command to switch to the casting weapon
    melee_weapon_cmd: str = ""     # full command to switch to the melee weapon


@dataclass
class StealthConfig:
    auto_sneak: bool = False
    sneak_cmd: str = "sneak"
    must_sneak: bool = False
    auto_hide: bool = False
    hide_cmd: str = "hide"


@dataclass
class NavigationConfig:
    loop_path: str = ""
    start_room: str = ""
    auto_start: bool = False
    flee_rooms: int = 3
    can_pick_locks: bool = False
    can_disarm_traps: bool = False


@dataclass
class ItemsConfig:
    auto_get: bool = False
    auto_cash: bool = True
    collect_copper: bool = True
    collect_silver: bool = True
    collect_gold: bool = True
    collect_platinum: bool = True
    collect_runic: bool = False
    runic_name: str = "runic"
    dont_go_heavy: bool = True
    dont_go_medium: bool = False


@dataclass
class PartyBless:
    cmd: str = ""
    wait_seconds: int = 60


@dataclass
class PartyConfig:
    heal_spell: str = ""
    heal_hp_pct: float = 0.50
    wait_hp_pct: float = 0.30
    wait_max_seconds: int = 30
    wait_cmd: str = "wait"
    resume_cmd: str = "go"
    attack_with_leader: bool = True
    share_cash: bool = False
    bless: list[PartyBless] = field(default_factory=list)


@dataclass
class AfkConfig:
    enabled: bool = False
    timeout_minutes: int = 5
    reply: str = "I am AFK"
    hangup_on_low_hp: bool = False
    alert: bool = False
    popup_missed: bool = True


@dataclass
class HealthConfig:
    blind_cmd: str = ""      # cure blindness, e.g. "cast purify vision"
    poison_cmd: str = ""     # cure poison
    disease_cmd: str = ""    # cure disease
    freedom_cmd: str = ""    # break hold/paralysis


@dataclass
class SafetyConfig:
    hangup_on_death: bool = True
    hangup_players: list[str] = field(default_factory=list)  # disconnect if seen in room
    panic_cmd: str = ""      # sent before a panic hangup (e.g. "recall")
    reconnect: bool = False  # auto-reconnect on connection loss
    max_redials: int = 3


@dataclass
class RemoteConfig:
    enabled: bool = False    # opt-in: remote commands off unless explicitly enabled
    # Reply template; MajorMud telepath syntax. Adjust to the live server's syntax
    # ("/<name> <text>" or "telepath <name> <text>") during in-person testing.
    tell_format: str = "/{name} {text}"


@dataclass
class PvpConfig:
    action: str = ""               # "" ignore | "attack" | "flee" | "hangup" | command string
    spell: str = ""                # cast at the player when action == "attack"
    flee_rooms: int = 2
    hangup_delay_s: int = 0        # delay before hangup when action == "hangup"


@dataclass
class PlayerRule:
    name: str = ""
    friend: bool = False
    remote_cmds: list[str] = field(default_factory=list)
    dont_heal: bool = False
    dont_bless: bool = False


@dataclass
class UiConfig:
    show_right_panel: bool = True
    show_stats_bar: bool = True
    default_tab: str = "conversations"  # "conversations" | "players" | "stats"


@dataclass
class MudConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    login: LoginConfig = field(default_factory=LoginConfig)
    combat: CombatConfig = field(default_factory=CombatConfig)
    spells: SpellsConfig = field(default_factory=SpellsConfig)
    stealth: StealthConfig = field(default_factory=StealthConfig)
    navigation: NavigationConfig = field(default_factory=NavigationConfig)
    items: ItemsConfig = field(default_factory=ItemsConfig)
    party: PartyConfig = field(default_factory=PartyConfig)
    afk: AfkConfig = field(default_factory=AfkConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    pvp: PvpConfig = field(default_factory=PvpConfig)
    players: list[PlayerRule] = field(default_factory=list)
    ui: UiConfig = field(default_factory=UiConfig)

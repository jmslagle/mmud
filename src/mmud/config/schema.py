from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ServerConfig:
    host: str = "localhost"
    port: int = 4000


@dataclass
class LoginStep:
    """One step of a scripted login: wait for `prompt`, then send `reply`.

    Mirrors the original MegaMud's LogonPrompt%d / LogonReply%d table. `prompt`
    is a case-insensitive regex; `reply` is template-expanded (`{userid}`,
    `{pswd}`, `{character}`). An empty `reply` just presses Enter.
    """
    prompt: str = ""
    reply: str = ""


@dataclass
class LoginConfig:
    username: str = ""
    password: str = ""
    character: str = ""
    auto_login: bool = False   # must be explicitly true to enable auto-login
    # Optional regex overrides for servers whose prompts differ from the
    # built-in defaults (which cover Worldgroup/Galacticomm + common MUDs).
    # Case-insensitive; "" = use the default pattern.
    username_prompt: str = ""
    password_prompt: str = ""
    # Authentic MegaMud-style scripted login: an ordered list of expect/reply
    # steps. When non-empty it DRIVES login (the built-in detection is the
    # zero-config fallback). `menu_prompt` (regex) marks "now in the game".
    menu_prompt: str = ""
    script: list[LoginStep] = field(default_factory=list)


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
    attack_neutral: bool = False   # also attack kill-type-3 (neutral) monsters;
                                   # MegaMud's "AttackNeutral" toggle. Off = only
                                   # attack hostile (kill-type 4); never NPCs (2/5).


@dataclass
class BlessSpell:
    cmd: str = ""
    mana_pct: float = 0.80          # only (re)cast at/above this mana %
    interval_s: float = 600.0       # re-cast every N seconds (MegaMud's flat ~600)
    refresh_on: str = ""            # regex of the buff's fade line -> recast at once


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
    # MegaMud hardcodes the sneak/hide verbs in automation (literals "sneak"/
    # "hide" — see docs/megamud-commands-reference.md §3); only the enable toggle
    # is configurable, mirroring MegaMud's AutoSneak key.
    auto_sneak: bool = False
    must_sneak: bool = False


@dataclass
class NavigationConfig:
    loop_path: str = ""
    auto_start: bool = False
    flee_rooms: int = 3
    can_pick_locks: bool = False
    can_disarm_traps: bool = False
    auto_search: bool = False   # search for hidden exits in each new room
    search_max: int = 3         # search attempts per room
    roam: bool = False          # wander random exits when idle
    bash_doors: bool = False    # bash closed doors when open fails


@dataclass
class ItemsConfig:
    auto_get: bool = False
    auto_cash: bool = True
    inventory_cmd: str = "inv"   # command that lists inventory ("i"/"inventory" on some servers)
    collect_copper: bool = True
    collect_silver: bool = True
    collect_gold: bool = True
    collect_platinum: bool = True
    collect_runic: bool = False
    dont_go_heavy: bool = True
    dont_go_medium: bool = False
    max_wealth: int = 0    # bank when copper-equiv wealth exceeds (Phase 8 consumes)
    min_wealth: int = 0    # withdraw when below (Phase 8 consumes)


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
    status_cmd: str = ""           # command that prints the party list ("" = off)
    status_interval_s: int = 60    # refresh cadence


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
    look_players: bool = True      # auto "l <name>" at unknown players (MegaMud LookPlayers)


@dataclass
class LearningConfig:
    enabled: bool = False            # opt-in: use the GameStore + learning hooks
    store_path: str = "gamedb.json"  # JSON store location (relative to CWD)


@dataclass
class CommerceConfig:
    bank_room: str = ""      # 4-letter room code; "" = banking disabled
    shop_room: str = ""      # "" = shopping disabled
    train_room: str = ""     # "" = training travel disabled
    sell_items: list[str] = field(default_factory=list)  # sell these when carried
    buy_items: list[str] = field(default_factory=list)   # keep these in inventory
    auto_train: bool = False


@dataclass
class SessionConfig:
    capture_file: str = ""          # append raw server lines here ("" = off)
    debug_log: str = ""             # human-readable RX/TX/event session log ("" = off)
    max_hours_per_day: int = 0      # hangup after this many hours (0 = unlimited)
    min_exp_rate: int = 0           # exp/hour floor (0 = disabled)
    grace_minutes: int = 15         # no rate enforcement during warmup
    low_rate_action: str = "hangup" # "hangup" | "relog"
    logout_cmd: str = "x"           # command that exits the game cleanly


@dataclass
class ScheduleEvent:
    type: str = "command"      # logon|logoff|relog|goto|command|loop
    every_seconds: int = 0     # fire interval (<=0 = disabled)
    count: int = 0             # times to fire (0 = forever)
    arg: str = ""              # room code / command template / loop name


@dataclass
class ScheduleConfig:
    events: list[ScheduleEvent] = field(default_factory=list)


@dataclass
class PlayerRule:
    name: str = ""
    friend: bool = False
    remote_cmds: list[str] = field(default_factory=list)
    dont_heal: bool = False


@dataclass
class UiConfig:
    show_right_panel: bool = True
    show_stats_bar: bool = True
    default_tab: str = "conversations"  # "conversations" | "players" | "stats"


@dataclass
class WebConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8080


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
    learning: LearningConfig = field(default_factory=LearningConfig)
    commerce: CommerceConfig = field(default_factory=CommerceConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    players: list[PlayerRule] = field(default_factory=list)
    ui: UiConfig = field(default_factory=UiConfig)
    web: WebConfig = field(default_factory=WebConfig)

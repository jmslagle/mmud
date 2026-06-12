export interface PanelState {
  terminal: string[];            // recent game lines (ANSI preserved)
  room: { code: string; name: string };
  vitals: { hp: number; maxHp: number; mana: number; maxMana: number; inCombat: boolean };
  progress: { level: number; exp: number; kills: number };
  combat: {
    hits: number; misses: number; special: number; dmgSum: number;
    monsterHits: number; monsterMisses: number;
    backstabAttempts: number; backstabSuccesses: number;
    hitPct: number; avgDamage: number;
  };
  session: { hoursElapsed: number; expRatePerHour: number; stats: Record<string, string> };
  conversations: { channel: string; sender: string; text: string }[];
  players: Record<string, { name: string; level: string; rep: string; gang: string }>;
  monsters: { name: string; count: number; expEach: number }[];
  conditions: Record<string, boolean>;
  activity: string;              // latest task/travel status line
}

export type PanelEvent = { type: string; [k: string]: any };

export const initialPanelState: PanelState = {
  terminal: [],
  room: { code: "", name: "" },
  vitals: { hp: 0, maxHp: 0, mana: 0, maxMana: 0, inCombat: false },
  progress: { level: 0, exp: 0, kills: 0 },
  combat: {
    hits: 0, misses: 0, special: 0, dmgSum: 0,
    monsterHits: 0, monsterMisses: 0,
    backstabAttempts: 0, backstabSuccesses: 0, hitPct: 0, avgDamage: 0,
  },
  session: { hoursElapsed: 0, expRatePerHour: 0, stats: {} },
  conversations: [],
  players: {},
  monsters: [],
  conditions: {},
  activity: "",
};

const TERMINAL_MAX = 500;
const CONVO_MAX = 200;

export function panelReducer(state: PanelState, ev: PanelEvent): PanelState {
  switch (ev.type) {
    case "Snapshot":
      return {
        ...state,
        room: { code: ev.room.code, name: state.room.name },
        vitals: {
          hp: ev.vitals.hp, maxHp: ev.vitals.max_hp,
          mana: ev.vitals.mana, maxMana: ev.vitals.max_mana,
          inCombat: ev.vitals.in_combat,
        },
        progress: { level: ev.progress.level, exp: ev.progress.exp, kills: ev.progress.kills },
        combat: {
          hits: ev.combat.hits, misses: ev.combat.misses,
          special: ev.combat.special, dmgSum: ev.combat.dmg_sum,
          monsterHits: ev.combat.monster_hits, monsterMisses: ev.combat.monster_misses,
          backstabAttempts: ev.combat.backstab_attempts,
          backstabSuccesses: ev.combat.backstab_successes,
          hitPct: ev.combat.hit_pct, avgDamage: ev.combat.avg_damage,
        },
        session: {
          ...state.session,
          hoursElapsed: ev.session.hours_elapsed,
          expRatePerHour: ev.session.exp_rate_per_hour,
        },
        monsters: ev.monsters.map((m: any) => ({
          name: m.name, count: m.count, expEach: m.exp_each,
        })),
        players: ev.players.reduce(
          (acc: PanelState["players"], name: string) => {
            acc[name] = acc[name] ?? { name, level: "", rep: "", gang: "" };
            return acc;
          },
          { ...state.players },
        ),
      };
    case "LineReceived":
      return { ...state, terminal: [...state.terminal, ev.line].slice(-TERMINAL_MAX) };
    case "HpChanged":
      return { ...state, vitals: { ...state.vitals, hp: ev.hp, maxHp: ev.max_hp } };
    case "MpChanged":
      return { ...state, vitals: { ...state.vitals, mana: ev.mp, maxMana: ev.max_mp } };
    case "RoomChanged":
      return { ...state, room: { code: ev.code, name: ev.name } };
    case "CombatChanged":
      return { ...state, vitals: { ...state.vitals, inCombat: ev.in_combat } };
    case "ConversationReceived":
      return {
        ...state,
        conversations: [
          ...state.conversations,
          { channel: ev.channel, sender: ev.sender, text: ev.text },
        ].slice(-CONVO_MAX),
      };
    case "PlayerSeen":
      return {
        ...state,
        players: {
          ...state.players,
          [ev.name]: { name: ev.name, level: ev.level, rep: ev.rep, gang: ev.gang },
        },
      };
    case "MonstersSeen":
      return {
        ...state,
        monsters: ev.monsters.map((n: string) => ({ name: n, count: 1, expEach: 0 })),
      };
    case "ConditionChanged":
      return { ...state, conditions: { ...state.conditions, [ev.name]: ev.active } };
    case "SessionStatUpdated":
      return {
        ...state,
        session: { ...state.session, stats: { ...state.session.stats, [ev.key]: ev.value } },
      };
    case "TaskChanged":
      return { ...state, activity: `${ev.task_type}: ${ev.status}` };
    case "PathStarted":
      return { ...state, activity: `path ${ev.name}` };
    case "PathStepped":
      return { ...state, activity: `${ev.command} (lap ${ev.lap})` };
    case "TravelResynced":
      return { ...state, activity: `resync ${ev.from_step}->${ev.to_step}` };
    case "TravelEnded":
      return { ...state, activity: `travel ${ev.reason}` };
    case "HangupTriggered":
      return { ...state, activity: `HANGUP: ${ev.reason}` };
    default:
      return state;
  }
}

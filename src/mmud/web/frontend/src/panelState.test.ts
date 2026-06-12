import { describe, it, expect } from "vitest";
import { initialPanelState, panelReducer } from "./panelState";

describe("panelReducer", () => {
  it("appends terminal lines", () => {
    const s = panelReducer(initialPanelState, { type: "LineReceived", line: "hello" });
    expect(s.terminal).toEqual(["hello"]);
  });

  it("updates hp", () => {
    const s = panelReducer(initialPanelState, { type: "HpChanged", hp: 12, max_hp: 40 });
    expect(s.vitals.hp).toBe(12);
    expect(s.vitals.maxHp).toBe(40);
  });

  it("collects conversations", () => {
    const s = panelReducer(initialPanelState, {
      type: "ConversationReceived", channel: "tell", sender: "Bob", text: "hi",
    });
    expect(s.conversations).toEqual([{ channel: "tell", sender: "Bob", text: "hi" }]);
  });

  it("indexes players by name", () => {
    const s = panelReducer(initialPanelState, {
      type: "PlayerSeen", name: "Bob", level: "L5", rep: "Neutral", gang: "G",
    });
    expect(s.players["Bob"]).toEqual({ name: "Bob", level: "L5", rep: "Neutral", gang: "G" });
  });

  it("tracks session stats by key", () => {
    const s = panelReducer(initialPanelState, {
      type: "SessionStatUpdated", key: "kills", value: "7",
    });
    expect(s.session.stats["kills"]).toBe("7");
  });

  it("hydrates from a Snapshot", () => {
    const snap = {
      type: "Snapshot",
      room: { code: "ABCD", hex: "1A" },
      vitals: { hp: 5, max_hp: 50, mana: 1, max_mana: 9, in_combat: true },
      progress: { level: 3, exp: 1000, kills: 2 },
      combat: {
        hits: 10, misses: 2, special: 1, dmg_sum: 80,
        monster_hits: 4, monster_misses: 3,
        backstab_attempts: 2, backstab_successes: 1, hit_pct: 80, avg_damage: 8,
      },
      session: { hours_elapsed: 1.5, exp_rate_per_hour: 666 },
      monsters: [{ name: "rat", count: 2, exp_each: 5 }],
      players: ["Bob"],
    };
    const s = panelReducer(initialPanelState, snap);
    expect(s.vitals.hp).toBe(5);
    expect(s.progress.level).toBe(3);
    expect(s.combat.hitPct).toBe(80);
    expect(s.session.expRatePerHour).toBe(666);
    expect(s.monsters[0]).toEqual({ name: "rat", count: 2, expEach: 5 });
    expect(s.players["Bob"].name).toBe("Bob");
  });

  it("ignores unknown event types", () => {
    const s = panelReducer(initialPanelState, { type: "Nope" });
    expect(s).toBe(initialPanelState);
  });
});

import { describe, it, expect, vi } from "vitest";
import { routeRawOutput } from "./useWebSocket";

describe("routeRawOutput", () => {
  it("writes RawOutput.data to the terminal sink", () => {
    const write = vi.fn();
    routeRawOutput({ type: "RawOutput", data: "\x1b[2Jhi" }, write);
    expect(write).toHaveBeenCalledWith("\x1b[2Jhi");
  });

  it("ignores non-RawOutput events", () => {
    const write = vi.fn();
    routeRawOutput({ type: "HpChanged", hp: 1, max_hp: 2 }, write);
    expect(write).not.toHaveBeenCalled();
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { get } from "svelte/store";

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn().mockResolvedValue(() => {}),
}));

Object.defineProperty(window, "__TAURI_INTERNALS__", {
  value: {},
  writable: true,
  configurable: true,
});

describe("deviceState store", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("initialises with SSD absent", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).ssd_mounted).toBe(false);
  });

  it("initialises with ssd_label null", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).ssd_label).toBeNull();
  });

  it("initialises with SD absent", async () => {
    const { deviceState } = await import("./devices");
    expect(get(deviceState).sd_mounted).toBe(false);
  });

  it("can be set to mounted state", async () => {
    const { deviceState } = await import("./devices");
    deviceState.set({ ssd_mounted: true, ssd_label: "PHOTON-001", ssd_mount_point: "/media/alex/PHOTON-001", sd_mounted: true, sd_path: "/media/alex/SD" });
    const state = get(deviceState);
    expect(state.ssd_mounted).toBe(true);
    expect(state.ssd_label).toBe("PHOTON-001");
    expect(state.sd_mounted).toBe(true);
  });
});

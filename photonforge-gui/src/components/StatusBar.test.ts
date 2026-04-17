import { describe, it, expect, vi, beforeEach } from "vitest";
import { render } from "@testing-library/svelte";
import { writable } from "svelte/store";

const mockDeviceState = writable({
  ssd_mounted: false,
  ssd_label: null as string | null,
  sd_mounted: false,
});

vi.mock("../stores/devices", () => ({
  deviceState: mockDeviceState,
}));

const { default: StatusBar } = await import("./StatusBar.svelte");

describe("StatusBar", () => {
  beforeEach(() => {
    mockDeviceState.set({ ssd_mounted: false, ssd_label: null, sd_mounted: false });
  });

  it("shows 'No cartridge' when SSD absent", () => {
    const { getByText } = render(StatusBar);
    expect(getByText(/No cartridge/)).toBeInTheDocument();
  });

  it("shows 'No SD card' when SD absent", () => {
    const { getByText } = render(StatusBar);
    expect(getByText(/No SD card/)).toBeInTheDocument();
  });

  it("shows SSD label when mounted", async () => {
    mockDeviceState.set({ ssd_mounted: true, ssd_label: "PHOTON-001", sd_mounted: false });
    const { getByText } = render(StatusBar);
    expect(getByText(/PHOTON-001/)).toBeInTheDocument();
  });

  it("shows 'SD ready' when SD mounted", async () => {
    mockDeviceState.set({ ssd_mounted: false, ssd_label: null, sd_mounted: true });
    const { getByText } = render(StatusBar);
    expect(getByText(/SD ready/)).toBeInTheDocument();
  });
});

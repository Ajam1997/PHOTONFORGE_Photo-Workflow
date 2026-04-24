import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import IngestDashboard from "./IngestDashboard.svelte";
import { deviceState } from "../stores/devices";
import type { DeviceState } from "../stores/devices";

vi.mock("../lib/sidecar", () => ({
  runIngest: vi.fn(),
}));

import { runIngest } from "../lib/sidecar";

function setDeviceState(state: Partial<DeviceState>) {
  deviceState.set({
    ssd_mounted: false,
    ssd_label: null,
    ssd_mount_point: null,
    sd_mounted: false,
    sd_path: null,
    ...state,
  });
}

describe("IngestDashboard", () => {
  beforeEach(() => {
    setDeviceState({});
    vi.clearAllMocks();
  });

  it("Start Ingest disabled when ssd_mounted is false", () => {
    setDeviceState({ sd_mounted: true, sd_path: "/media/alex/SD", ssd_mounted: false });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).toBeDisabled();
  });

  it("Start Ingest disabled when sd_mounted is false", () => {
    setDeviceState({ ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001", sd_mounted: false });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).toBeDisabled();
  });

  it("Start Ingest enabled when both SD and SSD present", () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001", ssd_label: "PHOTON-001",
    });
    render(IngestDashboard);
    const btn = screen.getByRole("button", { name: /start ingest/i });
    expect(btn).not.toBeDisabled();
  });

  it("Shows warning when SD absent", () => {
    setDeviceState({ ssd_mounted: true });
    render(IngestDashboard);
    expect(screen.getByText(/insert sd card/i)).toBeInTheDocument();
  });

  it("Shows warning when SSD absent", () => {
    setDeviceState({ sd_mounted: true });
    render(IngestDashboard);
    expect(screen.getByText(/no cartridge mounted/i)).toBeInTheDocument();
  });

  it("Shows progress bar and cancel button while running", async () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001",
    });

    let capturedCallback: ((e: any) => void) | null = null;
    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      capturedCallback = cb;
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => expect(capturedCallback).not.toBeNull());
    capturedCallback!({ type: "progress", step: "copying", current: 42, total: 150, message: "" });

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /cancel/i })).toBeInTheDocument();
    });
  });

  it("Shows summary card after done event", async () => {
    setDeviceState({
      sd_mounted: true, sd_path: "/media/alex/SD",
      ssd_mounted: true, ssd_mount_point: "/mnt/photon_ssd/001",
    });

    vi.mocked(runIngest).mockImplementation(async (_s, _o, _d, cb) => {
      setTimeout(() => cb({
        type: "done",
        summary: { total: 150, duplicates_skipped: 8, scored: 142, named: 142, xmp_written: 142, db_upserted: 142, elapsed_seconds: 47.2 },
      }), 0);
      return { kill: vi.fn() } as any;
    });

    render(IngestDashboard);
    fireEvent.click(screen.getByRole("button", { name: /start ingest/i }));

    await waitFor(() => {
      expect(screen.getByText("150")).toBeInTheDocument();
      expect(screen.getByText("8")).toBeInTheDocument();
    });
    expect(screen.getByRole("button", { name: /new ingest/i })).toBeInTheDocument();
  });
});

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/svelte";
import CartridgeManager from "./CartridgeManager.svelte";

vi.mock("../lib/sidecar", () => ({
  listCartridges: vi.fn(),
  reformatCartridge: vi.fn(),
}));

import { listCartridges, reformatCartridge } from "../lib/sidecar";

const mockCartridges = [
  {
    label: "PHOTON-001",
    mount_point: "/mnt/photon_ssd/001",
    free_bytes: 214_748_364_800,
    size_bytes: 500_107_862_016,
  },
];

describe("CartridgeManager", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(listCartridges).mockResolvedValue(mockCartridges);
  });

  it("renders cartridge card from mock sidecar cartridges event", async () => {
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText("PHOTON-001")).toBeInTheDocument();
      expect(screen.getByText("/mnt/photon_ssd/001")).toBeInTheDocument();
    });
  });

  it("reformat confirm button disabled until label typed correctly", async () => {
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /confirm reformat/i });
      expect(btn).toBeDisabled();
    });
  });

  it("reformat confirm button enabled when label matches", async () => {
    render(CartridgeManager);
    await waitFor(() => screen.getByText("PHOTON-001"));

    fireEvent.click(screen.getByRole("button", { name: /reformat/i }));
    await waitFor(() => screen.getByLabelText(/type the cartridge label/i));

    const input = screen.getByLabelText(/type the cartridge label/i);
    fireEvent.input(input, { target: { value: "PHOTON-001" } });

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /confirm reformat/i });
      expect(btn).not.toBeDisabled();
    });
  });

  it("shows empty state when no cartridges mounted", async () => {
    vi.mocked(listCartridges).mockResolvedValue([]);
    render(CartridgeManager);
    await waitFor(() => {
      expect(screen.getByText(/no photon cartridges mounted/i)).toBeInTheDocument();
    });
  });
});

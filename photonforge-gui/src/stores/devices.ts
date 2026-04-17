import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";

export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  sd_mounted: boolean;
}

const initial: DeviceState = {
  ssd_mounted: false,
  ssd_label: null,
  sd_mounted: false,
};

export const deviceState = writable<DeviceState>(initial);

if (typeof window !== "undefined" && (window as any).__TAURI_INTERNALS__) {
  listen<DeviceState>("device-state-changed", (event) => {
    deviceState.set(event.payload);
  });
}

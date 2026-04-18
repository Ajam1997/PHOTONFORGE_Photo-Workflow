import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

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

if (typeof window !== "undefined") {
  // Pull current state immediately via invoke (no race with event timing).
  invoke<DeviceState>("get_device_state")
    .then((state) => deviceState.set(state))
    .catch(() => {});

  // Subscribe to future changes.
  listen<DeviceState>("device-state-changed", (event) => {
    deviceState.set(event.payload);
  }).catch(() => {});
}

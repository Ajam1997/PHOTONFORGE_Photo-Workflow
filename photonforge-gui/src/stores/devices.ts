import { writable } from "svelte/store";
import { listen } from "@tauri-apps/api/event";
import { invoke } from "@tauri-apps/api/core";

export interface DeviceState {
  ssd_mounted: boolean;
  ssd_label: string | null;
  ssd_mount_point: string | null;
  sd_mounted: boolean;
  sd_path: string | null;
}

const initial: DeviceState = {
  ssd_mounted: false,
  ssd_label: null,
  ssd_mount_point: null,
  sd_mounted: false,
  sd_path: null,
};

export const deviceState = writable<DeviceState>(initial);

if (typeof window !== "undefined") {
  invoke<DeviceState>("get_device_state")
    .then((state) => deviceState.set(state))
    .catch(() => {});

  listen<DeviceState>("device-state-changed", (event) => {
    deviceState.set(event.payload);
  }).catch(() => {});
}

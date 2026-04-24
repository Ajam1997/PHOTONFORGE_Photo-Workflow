import { writable } from "svelte/store";
import type { DoneEvent } from "../lib/sidecar";
import type { Command } from "@tauri-apps/plugin-shell";

export type IngestPhase = "idle" | "running" | "done";

export interface IngestState {
  phase: IngestPhase;
  step: string;
  current: number;
  total: number;
  summary: DoneEvent["summary"] | null;
  errorMsg: string;
  activeCmd: Command<string> | null;
  stageDone: Record<string, Record<string, number>>;
  sdEjected: boolean;
}

const initial: IngestState = {
  phase: "idle",
  step: "copy",
  current: 0,
  total: 0,
  summary: null,
  errorMsg: "",
  activeCmd: null,
  stageDone: {},
  sdEjected: false,
};

export const ingestState = writable<IngestState>({ ...initial });

export function resetIngest() {
  ingestState.set({ ...initial });
}

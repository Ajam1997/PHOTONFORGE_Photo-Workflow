import { writable } from "svelte/store";

export interface PipelineSettings {
  dedup: boolean;
  scoring: boolean;
  naming: boolean;
  darktable: boolean;
}

const STORAGE_KEY = "photon.pipeline";

const defaults: PipelineSettings = {
  dedup: true,
  scoring: true,
  naming: true,
  darktable: true,
};

function load(): PipelineSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...defaults, ...JSON.parse(raw) };
  } catch { /* ignore parse errors */ }
  return { ...defaults };
}

export const pipelineSettings = writable<PipelineSettings>(load());

pipelineSettings.subscribe((value) => {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  } catch { /* ignore write errors */ }
});

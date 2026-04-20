import { Command } from "@tauri-apps/plugin-shell";

export interface ProgressEvent {
  type: "progress";
  step: string;
  current: number;
  total: number;
  message: string;
}

export interface DoneEvent {
  type: "done";
  summary: {
    total: number;
    duplicates_skipped: number;
    scored: number;
    xmp_written: number;
    db_upserted: number;
    elapsed_seconds: number;
  };
}

export interface ErrorEvent {
  type: "error";
  message: string;
}

export interface CartridgesEvent {
  type: "cartridges";
  items: CartridgeInfo[];
}

export interface ReformatDoneEvent {
  type: "reformat_done";
  label: string;
  mount_point: string;
}

export interface CartridgeInfo {
  label: string;
  mount_point: string;
  free_bytes: number;
  size_bytes: number;
}

export type SidecarEvent =
  | ProgressEvent
  | DoneEvent
  | ErrorEvent
  | CartridgesEvent
  | ReformatDoneEvent;

function parseLine(line: string): SidecarEvent | null {
  try {
    return JSON.parse(line) as SidecarEvent;
  } catch {
    return null;
  }
}

export async function runIngest(
  source: string,
  output: string,
  db: string,
  onEvent: (event: SidecarEvent) => void,
): Promise<Command<string>> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "ingest",
    "--source", source,
    "--output", output,
    "--db", db,
  ]);

  let buffer = "";
  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) onEvent(event);
    }
  });

  await cmd.spawn();
  return cmd;
}

export async function listCartridges(): Promise<CartridgeInfo[]> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "cartridge-list",
  ]);

  return new Promise((resolve, reject) => {
    let output = "";
    cmd.stdout.on("data", (chunk: string) => { output += chunk; });
    cmd.on("close", () => {
      for (const line of output.split("\n")) {
        const event = parseLine(line.trim());
        if (event?.type === "cartridges") {
          resolve(event.items);
          return;
        }
      }
      resolve([]);
    });
    cmd.on("error", reject);
    cmd.spawn().catch(reject);
  });
}

export async function reformatCartridge(
  device: string,
  label: string,
  onEvent: (event: SidecarEvent) => void,
  dryRun = false,
): Promise<Command<string>> {
  const args = [
    "cartridge-reformat",
    "--device", device,
    "--label", label,
  ];
  if (dryRun) args.push("--dry-run");

  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", args);

  let buffer = "";
  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) onEvent(event);
    }
  });

  await cmd.spawn();
  return cmd;
}

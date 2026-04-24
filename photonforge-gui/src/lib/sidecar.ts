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
    named: number;
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

export interface StageDoneEvent {
  type: "stage_done";
  stage: "copy" | "dedup" | "scoring" | "naming" | "darktable";
  copied?: number;
  dupes_found?: number;
  scored?: number;
  named?: number;
  xmp_written?: number;
  db_upserted?: number;
}

export interface SdEjectedEvent {
  type: "sd_ejected";
}

export interface ProvisionDoneEvent {
  type: "provision_done";
  label: string;
  device: string;
  mount_point: string;
  created_partition: boolean;
  wiped_signatures: boolean;
}

export type ProvisionEvent = ProgressEvent | ProvisionDoneEvent | ErrorEvent;

export interface CartridgeInfo {
  label: string;
  mount_point: string;
  free_bytes: number;
  size_bytes: number;
}

export interface DriveInfo {
  device: string;
  size_bytes: number;
  model: string;
  label: string | null;
}

export interface DrivesEvent {
  type: "drives";
  items: DriveInfo[];
}

export type SidecarEvent =
  | ProgressEvent
  | DoneEvent
  | ErrorEvent
  | CartridgesEvent
  | ReformatDoneEvent
  | ProvisionDoneEvent
  | StageDoneEvent
  | SdEjectedEvent
  | DrivesEvent;

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
  options: {
    skipDedup?: boolean;
    skipScoring?: boolean;
    skipNaming?: boolean;
    skipDarktable?: boolean;
    modelDir?: string;
  } = {},
): Promise<Command<string>> {
  const args = ["ingest", "--source", source, "--output", output, "--db", db];
  if (options.modelDir) args.push("--model-dir", options.modelDir);
  if (options.skipDedup) args.push("--skip-dedup");
  if (options.skipScoring) args.push("--skip-scoring");
  if (options.skipNaming) args.push("--skip-naming");
  if (options.skipDarktable) args.push("--skip-darktable");

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

export async function listDrives(): Promise<DriveInfo[]> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", ["list-drives"]);
  const result = await cmd.execute();
  for (const line of result.stdout.split("\n")) {
    const event = parseLine(line.trim());
    if (event?.type === "drives") return (event as DrivesEvent).items;
  }
  return [];
}

export async function listCartridges(): Promise<CartridgeInfo[]> {
  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", [
    "cartridge-list",
  ]);
  const result = await cmd.execute();
  for (const line of result.stdout.split("\n")) {
    const event = parseLine(line.trim());
    if (event?.type === "cartridges") return event.items;
  }
  return [];
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

export async function provisionCartridge(
  device: string,
  label: string,
  forceRepartition: boolean,
  dryRun: boolean,
  onEvent: (event: ProvisionEvent) => void,
): Promise<Command<string>> {
  const args = ["cartridge-provision", "--device", device, "--label", label];
  if (forceRepartition) args.push("--force-repartition");
  if (dryRun) args.push("--dry-run");

  const cmd = Command.sidecar("binaries/photo-workflow-sidecar", args);

  let buffer = "";
  let done = false;

  cmd.stdout.on("data", (chunk: string) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const event = parseLine(line.trim());
      if (event) {
        if (event.type === "provision_done") done = true;
        onEvent(event as ProvisionEvent);
      }
    }
  });
  cmd.stderr.on("data", (line: string) => {
    console.error("provision stderr:", line);
  });
  cmd.on("close", (data) => {
    // Flush any remaining buffered line
    if (buffer.trim()) {
      const event = parseLine(buffer.trim());
      if (event) onEvent(event as ProvisionEvent);
    }
    if (!done && data.code !== 0) {
      onEvent({ type: "error", message: `Sidecar exited with code ${data.code}` });
    }
  });

  await cmd.spawn();
  return cmd;
}

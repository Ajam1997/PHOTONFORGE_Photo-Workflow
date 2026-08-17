local dt = require "darktable"
local M = {}

local SCRIPT = "photonforge"

local DEFS = {
  { name = "sd_path",      type = "string",  default = "",   label = "SD card path" },
  { name = "dest_path",    type = "string",  default = "",   label = "Destination path" },
  { name = "tz_offset",    type = "integer", default = 0,    label = "TZ offset (hours)", min = -12, max = 14 },
  { name = "run_mode",     type = "string",  default = "resume", label = "Run mode (resume/force/fresh)" },
  { name = "file_type",    type = "string",  default = "both",   label = "File type (raw/jpg/both)" },
  { name = "step_ingest",  type = "bool",    default = false, label = "Ingest (run once per photo set)" },
  { name = "step_import",  type = "bool",    default = false, label = "Import (run once per photo set)" },
  { name = "step_dedup",   type = "bool",    default = true, label = "Dedup" },
  { name = "step_score",   type = "bool",    default = true, label = "Score" },
  { name = "step_name",    type = "bool",    default = true, label = "Name" },
  { name = "corpus_path",      type = "string",  default = "", label = "Corpus JSONL path" },
  { name = "models_path",      type = "string",  default = "", label = "Models dir (blank = auto-detect from package)" },
  { name = "cli_path",         type = "string",  default = "", label = "photo-workflow CLI path (blank = 'photo-workflow' on PATH; set to <venv>/Scripts/photo-workflow.exe when Darktable can't see the venv)" },
  { name = "cartridge_path",   type = "string",  default = "", label = "photo-cartridge program path -- ADVANCED, leave blank (auto-derived). This is the .exe, NOT your cartridge drive" },
  { name = "dev_mode",         type = "bool",    default = false, label = "Developer mode panel (resolved command, timing, open log)" },
  { name = "cartridge_id",     type = "string",  default = "", label = "Cartridge ID (e.g. 003) for provisioning" },
  { name = "backup_dest",      type = "string",  default = "", label = "Backup destination (second drive, for verified cartridge mirrors)" },
  { name = "snapshot_keep",    type = "integer", default = 7,  label = "Catalog snapshots to keep", min = 1, max = 365 },
  { name = "backup_keep",      type = "integer", default = 10, label = "Cartridge mirrors to keep", min = 1, max = 365 },
  { name = "backup_repo",      type = "string",  default = "", label = "Backup repo (restic: local path or cloud, e.g. b2:bucket) — not implemented yet" },
  { name = "backup_pwfile",    type = "string",  default = "", label = "Backup password file (restic repo password) — not implemented yet" },
  { name = "last_run_ingest",  type = "string",  default = "", label = "" },
  { name = "last_run_import",  type = "string",  default = "", label = "" },
  { name = "last_run_dedup",   type = "string",  default = "", label = "" },
  { name = "last_run_score",   type = "string",  default = "", label = "" },
  { name = "last_run_name",    type = "string",  default = "", label = "" },
}

for _, d in ipairs(DEFS) do
  if d.type == "integer" then
    dt.preferences.register(
      SCRIPT, d.name, d.type, d.label, "PHOTONForge: " .. d.label, d.default, d.min, d.max
    )
  else
    dt.preferences.register(
      SCRIPT, d.name, d.type, d.label, "PHOTONForge: " .. d.label, d.default
    )
  end
end

function M.read(name)
  for _, d in ipairs(DEFS) do
    if d.name == name then
      return dt.preferences.read(SCRIPT, name, d.type)
    end
  end
  error("Unknown config key: " .. name)
end

function M.write(name, value)
  for _, d in ipairs(DEFS) do
    if d.name == name then
      dt.preferences.write(SCRIPT, name, d.type, value)
      return
    end
  end
  error("Unknown config key: " .. name)
end

return M

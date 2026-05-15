local dt = require "darktable"
local M = {}

local SCRIPT = "photonforge"

local DEFS = {
  { name = "sd_path",      type = "string",  default = "",   label = "SD card path" },
  { name = "dest_path",    type = "string",  default = "",   label = "Destination path" },
  { name = "model_dir",    type = "string",  default = "models/florence2_int8", label = "Model directory" },
  { name = "manifest",     type = "string",  default = "manifest.jsonl",   label = "Manifest path" },
  { name = "tz_offset",    type = "integer", default = 0,    label = "TZ offset (hours)", min = -12, max = 14 },
  { name = "step_ingest",  type = "bool",    default = true, label = "Ingest" },
  { name = "step_scan",    type = "bool",    default = true, label = "Scan" },
  { name = "step_dedup",   type = "bool",    default = true, label = "Dedup" },
  { name = "step_score",   type = "bool",    default = true, label = "Score" },
  { name = "step_name",    type = "bool",    default = true, label = "Name" },
  { name = "step_sync",    type = "bool",    default = false, label = "Sync (XMP)" },
  { name = "last_run_ingest",  type = "string",  default = "", label = "" },
  { name = "last_run_scan",    type = "string",  default = "", label = "" },
  { name = "last_run_dedup",   type = "string",  default = "", label = "" },
  { name = "last_run_score",   type = "string",  default = "", label = "" },
  { name = "last_run_name",    type = "string",  default = "", label = "" },
  { name = "last_run_sync",    type = "string",  default = "", label = "" },
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

local dt = require "darktable"
local json = require "photonforge/json"
local config = require "photonforge/config"
local applicator = require "photonforge/applicator"

local M = {}

M.abort = false

local function build_cmd(step)
  local manifest = config.read("manifest")
  local model_dir = config.read("model_dir")
  local tz = tostring(config.read("tz_offset"))
  local dest = config.read("dest_path")
  local sd = config.read("sd_path")

  local base = "photo-workflow " .. step .. " --json-progress"

  if step == "ingest" then
    return base .. ' --source "' .. sd .. '" --dest "' .. dest .. '"'
  elseif step == "scan" then
    return base .. ' --source "' .. dest .. '" --manifest "' .. manifest .. '"'
  elseif step == "dedup" then
    return base .. ' --manifest "' .. manifest .. '"'
  elseif step == "score" then
    return base .. ' --manifest "' .. manifest .. '"'
  elseif step == "name" then
    return base .. ' --manifest "' .. manifest .. '"'
              .. ' --model-dir "' .. model_dir .. '"'
              .. ' --tz-offset ' .. tz
  elseif step == "sync" then
    return base .. ' --manifest "' .. manifest .. '"'
  end
  error("Unknown step: " .. step)
end

function M.run_step(step, log_fn, job)
  M.abort = false
  local cmd = build_cmd(step)
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local handle = io.popen(cmd, "r")
  if handle == nil then
    log_fn("[ERROR] Failed to launch photo-workflow. Is it installed?")
    return false
  end

  local dest = config.read("dest_path")
  local done, total = 0, 0

  for line in handle:lines() do
    if M.abort then
      handle:close()
      log_fn("[STOPPED] Run aborted by user.")
      return false
    end

    local ok, rec = pcall(json.decode, line)
    if ok and type(rec) == "table" then
      if rec.step == "_progress" then
        done  = rec.done  or done
        total = rec.total or total
        if job ~= nil and total > 0 then
          job.percent = done / total
        end
      else
        local msg = string.format("[%s] %s %s [%s]",
          os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
        log_fn(msg)
        applicator.apply(rec, dest)
      end
    else
      log_fn(line)
    end
  end

  local ok_close = handle:close()
  return ok_close ~= false
end

function M.run_all(step_list, log_fn, status_fn)
  local total_steps = #step_list
  local job = dt.gui.create_job(
    "PHOTONForge (" .. total_steps .. " steps)", true,
    function() M.abort = true end
  )
  job.percent = 0.0

  for i, step in ipairs(step_list) do
    log_fn(string.format("--- Step %d/%d: %s ---", i, total_steps, step))
    local ok = M.run_step(step, log_fn, job)

    if step == "ingest" and ok then
      local dest = config.read("dest_path")
      local film = dt.films.new(dest)
      if film then
        log_fn("[ingest] Library rescanned: " .. dest)
      else
        log_fn("[ingest] Could not import folder: " .. dest)
      end
    end

    local result = ok and "ok" or "error"
    if status_fn ~= nil then
      status_fn(step, result, os.date("%Y-%m-%d %H:%M"))
    end

    if not ok then
      log_fn("[STOPPED] Step failed: " .. step .. ". Remaining steps skipped.")
      break
    end

    job.percent = i / total_steps
  end

  job:destroy()
end

return M

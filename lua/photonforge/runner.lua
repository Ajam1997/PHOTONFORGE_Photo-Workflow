local dt = require "darktable"
local json = require "photonforge/json"
local config = require "photonforge/config"
local applicator = require "photonforge/applicator"

local M = {}

M.abort = false

local IS_WINDOWS = package.config:sub(1,1) == "\\"

local function shell_quote(s)
  if IS_WINDOWS then
    s = s:gsub("\\$", "")
    return '"' .. s .. '"'
  end
  return "'" .. s:gsub("'", "'\\''") .. "'"
end

local function build_cmd(step)
  local manifest = config.read("manifest")
  local model_dir = config.read("model_dir")
  local tz = tostring(config.read("tz_offset"))
  local dest = config.read("dest_path")
  local sd = config.read("sd_path")

  local base = "photo-workflow " .. step .. " --json-progress"

  if step == "ingest" then
    return base .. " --source " .. shell_quote(sd) .. " --dest " .. shell_quote(dest)
  elseif step == "scan" then
    return base .. " --source " .. shell_quote(dest) .. " --manifest " .. shell_quote(manifest)
  elseif step == "dedup" then
    return base .. " --manifest " .. shell_quote(manifest)
  elseif step == "score" then
    return base .. " --manifest " .. shell_quote(manifest)
  elseif step == "name" then
    return base .. " --manifest " .. shell_quote(manifest)
              .. " --model-dir " .. shell_quote(model_dir)
              .. " --tz-offset " .. tz
  elseif step == "sync" then
    return base .. " --manifest " .. shell_quote(manifest)
  end
  error("Unknown step: " .. step)
end

local function exec_hidden(cmd)
  if IS_WINDOWS then
    local ps = 'powershell -WindowStyle Hidden -NoProfile -Command "& {' .. cmd .. '}"'
    os.execute(ps)
  else
    os.execute(cmd)
  end
end

local function is_process_alive()
  if IS_WINDOWS then
    local probe_file = os.getenv("TEMP") .. "\\photonforge_probe.txt"
    exec_hidden(
      'Get-Process -Name photo-workflow -ErrorAction SilentlyContinue | '
      .. 'Select-Object -First 1 Id | Out-File -Encoding ascii '
      .. "'" .. probe_file .. "'"
    )
    local fh = io.open(probe_file, "r")
    if fh then
      local content = fh:read("*a")
      fh:close()
      os.remove(probe_file)
      return content:find("%d") ~= nil
    end
    return false
  else
    local ret = os.execute("pgrep -f 'photo-workflow' >/dev/null 2>&1")
    return (ret == true or ret == 0)
  end
end

function M.kill()
  M.abort = true
  if IS_WINDOWS then
    exec_hidden('Stop-Process -Name photo-workflow -Force -ErrorAction SilentlyContinue')
    exec_hidden(
      "Get-Process python -ErrorAction SilentlyContinue | "
      .. "Where-Object { $_.MainWindowTitle -like 'photo-workflow*' } | "
      .. "Stop-Process -Force"
    )
  else
    os.execute("pkill -f 'photo-workflow' 2>/dev/null")
  end
end

local function get_log_path()
  if IS_WINDOWS then
    return os.getenv("TEMP") .. "\\photonforge_step.log"
  end
  return "/tmp/photonforge_step.log"
end

function M.run_step(step, log_fn, job)
  local cmd = build_cmd(step)
  local log_path = get_log_path()
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local f = io.open(log_path, "w")
  if f then f:close() end

  if IS_WINDOWS then
    local inner = cmd .. ' > ' .. shell_quote(log_path) .. ' 2>&1'
    inner = inner:gsub("'", "''")
    exec_hidden("Start-Process cmd -ArgumentList '/c'," .. "'" .. inner .. "'" .. " -WindowStyle Hidden")
  else
    cmd = cmd .. " > " .. shell_quote(log_path) .. " 2>&1 &"
    os.execute(cmd)
  end

  local dest = config.read("dest_path")
  local done, total = 0, 0
  local last_pos = 0
  local idle_count = 0
  local MAX_IDLE = 600

  while not M.abort do
    dt.control.sleep(500)

    local fh = io.open(log_path, "r")
    if fh == nil then
      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end

    fh:seek("set", last_pos)
    local new_data = fh:read("*a")
    last_pos = fh:seek()
    fh:close()

    if new_data == nil or new_data == "" then
      if not is_process_alive() then
        break
      end

      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end

    idle_count = 0
    for line in new_data:gmatch("[^\r\n]+") do
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

    ::continue::
  end

  if M.abort then
    M.kill()
    log_fn("[STOPPED] Run aborted by user.")
    return false
  end

  local fh = io.open(log_path, "r")
  if fh then
    fh:seek("set", last_pos)
    local remaining = fh:read("*a")
    fh:close()
    if remaining and remaining ~= "" then
      for line in remaining:gmatch("[^\r\n]+") do
        local ok, rec = pcall(json.decode, line)
        if ok and type(rec) == "table" and rec.step ~= "_progress" then
          local msg = string.format("[%s] %s %s [%s]",
            os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
          log_fn(msg)
          applicator.apply(rec, dest)
        elseif not ok then
          log_fn(line)
        end
      end
    end
  end

  return true
end

function M.run_all(step_list, log_fn, status_fn)
  M.abort = false
  local total_steps = #step_list
  local job = dt.gui.create_job(
    "PHOTONForge (" .. total_steps .. " steps)", true,
    function() M.kill() end
  )
  job.percent = 0.0

  for i, step in ipairs(step_list) do
    if M.abort then break end
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

  pcall(function() job.valid = false end)
  pcall(function() job:destroy() end)
end

return M

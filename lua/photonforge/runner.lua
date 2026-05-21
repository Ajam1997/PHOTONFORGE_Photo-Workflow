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

local function get_drive_root(path)
  if IS_WINDOWS then
    local drive = path:match("^(%a:\\)")
    if drive then return drive end
    local unc = path:match("^(\\\\[^\\]+\\[^\\]+\\)")
    if unc then return unc end
  end
  return "/"
end

local function get_db_path(dest)
  return get_drive_root(dest) .. "photonforge.db"
end

local function get_folder_name(dest)
  if IS_WINDOWS then
    return dest:match("([^\\]+)\\?$") or dest
  end
  return dest:match("([^/]+)/?$") or dest
end

local function build_cmd(step)
  local tz = tostring(config.read("tz_offset"))
  local dest = config.read("dest_path")
  local sd = config.read("sd_path")
  local run_mode = config.read("run_mode")

  local db = get_db_path(dest)
  local folder = get_folder_name(dest)
  local base = "photo-workflow " .. step .. " --json-progress"

  local mode_flag = ""
  if run_mode == "force" or run_mode == "fresh" then
    if step == "dedup" or step == "score" or step == "name" then
      mode_flag = " --force"
    end
  elseif run_mode == "resume" then
    if step == "score" or step == "name" then
      mode_flag = " --resume"
    end
  end

  if step == "ingest" then
    local file_type = config.read("file_type")
    local ft_flag = ""
    if file_type == "raw" or file_type == "jpg" then
      ft_flag = " --file-type " .. file_type
    end
    return base .. " --source " .. shell_quote(sd) .. " --dest " .. shell_quote(dest) .. ft_flag
  elseif step == "scan" then
    return base .. " --source " .. shell_quote(dest) .. " --db " .. shell_quote(db)
  elseif step == "dedup" then
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest) .. mode_flag
  elseif step == "score" then
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest) .. mode_flag
  elseif step == "name" then
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest)
              .. mode_flag
  end
  error("Unknown step: " .. step)
end

local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
end

local function get_log_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge_step.log"
end

local function get_sentinel_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.running"
end

local function get_pid_path()
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge.pid"
end

local function read_pid_file()
  local fh = io.open(get_pid_path(), "r")
  if not fh then return nil end
  local pid = fh:read("*l")
  fh:close()
  if pid then pid = pid:match("^%s*(%d+)%s*$") end
  return pid
end

local function is_process_alive()
  local fh = io.open(get_sentinel_path(), "r")
  if fh then
    fh:close()
    return true
  end
  return false
end

function M.kill()
  M.abort = true
  local pid = read_pid_file()
  if IS_WINDOWS then
    if pid then
      os.execute('taskkill /F /PID ' .. pid .. ' >nul 2>&1')
    end
  else
    if pid then
      os.execute("kill -9 " .. pid .. " 2>/dev/null")
    else
      os.execute("pkill -f 'photo-workflow' 2>/dev/null")
    end
  end
  os.remove(get_sentinel_path())
end

function M.run_import(log_fn, job)
  local ok = M.run_step("scan", log_fn, job)
  if not ok then return false end

  local dest = config.read("dest_path")
  log_fn(string.format("[%s] Importing %s into Darktable library...", os.date("%H:%M:%S"), dest))
  local result = dt.database.import(dest)
  if result then
    log_fn(string.format("[%s] Library imported: %s (%s images)", os.date("%H:%M:%S"), dest, tostring(result)))
  else
    log_fn(string.format("[%s] Could not import folder: %s", os.date("%H:%M:%S"), dest))
  end
  return true
end

function M.run_step(step, log_fn, job)
  if step == "import" then
    return M.run_import(log_fn, job)
  end

  local cmd = build_cmd(step)
  local log_path = get_log_path()
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local f = io.open(log_path, "w")
  if f then f:close() end

  if IS_WINDOWS then
    local bat_path = get_temp_dir() .. "\\photonforge_run.bat"
    local vbs_path = get_temp_dir() .. "\\photonforge_run.vbs"

    local bat = io.open(bat_path, "w")
    if bat then
      bat:write('@echo off\r\n')
      bat:write(cmd .. ' > "' .. log_path .. '" 2>&1\r\n')
      bat:close()
    end

    local vbs = io.open(vbs_path, "w")
    if vbs then
      vbs:write('CreateObject("Wscript.Shell").Run """' .. bat_path .. '""", 0, False\r\n')
      vbs:close()
    end

    os.execute('wscript "' .. vbs_path .. '"')
  else
    cmd = cmd .. " > " .. shell_quote(log_path) .. " 2>&1 &"
    os.execute(cmd)
  end

  local dest = config.read("dest_path")
  local done, total = 0, 0
  local last_pos = 0
  local idle_count = 0
  local MAX_IDLE = 600
  local startup_grace = 10

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
      if startup_grace > 0 then
        startup_grace = startup_grace - 1
      elseif not is_process_alive() then
        break
      end

      idle_count = idle_count + 1
      if idle_count > MAX_IDLE then break end
      goto continue
    end

    startup_grace = 0
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

  log_fn(string.format("[%s] Step finished (%d items)", os.date("%H:%M:%S"), done))
  return true
end

function M.run_all(step_list, log_fn, status_fn)
  M.abort = false

  local run_mode = config.read("run_mode")
  if run_mode == "fresh" then
    log_fn("[fresh] All steps will be re-run (DB preserved).")
  end

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
  log_fn(string.format("[%s] Pipeline complete.", os.date("%H:%M:%S")))
end

return M

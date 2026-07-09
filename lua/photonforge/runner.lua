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
    return path
  end
  -- Cartridge root = parent of the destination folder, matching the Python
  -- side (photondb puts photonforge.db at dest's parent). The old version
  -- returned "/" for every Linux path, pointing every command at the
  -- filesystem root.
  local parent = path:match("^(.-)/+[^/]+/*$")
  if parent and parent ~= "" then
    return parent .. "/"
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

local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
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
  elseif step == "dedup" then
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest) .. mode_flag
  elseif step == "score" then
    local cmd = base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest) .. mode_flag
    -- Pin the scoring model dir so CLIP/genre models load regardless of how the
    -- package is installed (a non-editable install cannot auto-detect models/).
    local models = config.read("models_path")
    if models ~= "" then
      cmd = cmd .. " --model-dir " .. shell_quote(models)
    end
    -- Use calibrated prototypes if training_weights.db is present on the cartridge
    local drive = get_drive_root(dest)
    local training_db = drive .. "training_weights.db"
    local fh = io.open(training_db, "r")
    if fh then
      fh:close()
      cmd = cmd .. " --training-db " .. shell_quote(training_db)
    end
    return cmd
  elseif step == "name" then
    local cmd = base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest)
              .. mode_flag
    -- The name (Florence-2) step expects the florence2_int8 subdir of models/.
    local models = config.read("models_path")
    if models ~= "" then
      local sep = IS_WINDOWS and "\\" or "/"
      cmd = cmd .. " --model-dir " .. shell_quote(models .. sep .. "florence2_int8")
    end
    return cmd

  elseif step == "sync-tags" then
    -- Push genres from photonforge.db into Darktable's library.db.
    -- Darktable always writes library.db next to its config dir.
    local dt_lib = dt.configuration.config_dir
    if IS_WINDOWS then
      dt_lib = dt_lib .. "\\library.db"
    else
      dt_lib = dt_lib .. "/library.db"
    end
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
              .. " --darktable-library " .. shell_quote(dt_lib)

  elseif step == "suggest-training-set" then
    -- Cluster needs_review embeddings and tag ~k representatives for labeling.
    return base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)

  elseif step == "refresh-review" then
    -- Recompute needs_review from cached embeddings (no image re-decode) and
    -- re-emit score recs so the applicator detaches stale photon|needs_review tags.
    local cmd = base .. " --db " .. shell_quote(db) .. " --folder " .. shell_quote(folder)
    local models = config.read("models_path")
    if models ~= "" then
      cmd = cmd .. " --model-dir " .. shell_quote(models)
    end
    local drive = get_drive_root(dest)
    local training_db = drive .. "training_weights.db"
    local fh = io.open(training_db, "r")
    if fh then
      fh:close()
      cmd = cmd .. " --training-db " .. shell_quote(training_db)
    end
    return cmd

  elseif step == "recalibrate" then
    -- Recalibrate genre prototypes from corpus labels.
    -- --model-dir omitted: auto-detected from package location.
    -- Output is plain text (no --json-progress); runner logs it as-is.
    local drive = get_drive_root(dest)
    local training_db = drive .. "training_weights.db"
    local cmd = "photo-workflow training recalibrate"
              .. " --photon-db " .. shell_quote(db)
              .. " --training-db " .. shell_quote(training_db)
    local models = config.read("models_path")
    if models ~= "" then
      cmd = cmd .. " --model-dir " .. shell_quote(models)
    end
    -- Corpus lives on the cartridge (portable with the library) unless overridden.
    local corpus = config.read("corpus_path")
    if corpus == "" then corpus = drive .. "genre_labels.jsonl" end
    cmd = cmd .. " --corpus " .. shell_quote(corpus)
    return cmd

  elseif step == "rescore" then
    -- Re-score with calibrated prototypes (used in correction loop).
    -- Uses --only-files manifest from collect-corrections to rescore
    -- just the corrected images; falls back to --force if no manifest.
    local tmp = get_temp_dir()
    local manifest = tmp .. (IS_WINDOWS and "\\" or "/") .. "photonforge_corrected_files.txt"
    local cmd = "photo-workflow score --json-progress"
              .. " --db "         .. shell_quote(db)
              .. " --folder "     .. shell_quote(folder)
              .. " --source-dir " .. shell_quote(dest)
    local mf = io.open(manifest, "r")
    if mf then
      mf:close()
      cmd = cmd .. " --only-files " .. shell_quote(manifest) .. " --skip-genre"
    else
      cmd = cmd .. " --force"
    end
    local models = config.read("models_path")
    if models ~= "" then
      cmd = cmd .. " --model-dir " .. shell_quote(models)
    end
    local drive = get_drive_root(dest)
    local training_db = drive .. "training_weights.db"
    local fh = io.open(training_db, "r")
    if fh then
      fh:close()
      cmd = cmd .. " --training-db " .. shell_quote(training_db)
    end
    return cmd

  elseif step == "collect-corrections" then
    -- Detect corrections made in Darktable and feed them back to the corpus.
    local dt_lib = dt.configuration.config_dir
    if IS_WINDOWS then
      dt_lib = dt_lib .. "\\library.db"
    else
      dt_lib = dt_lib .. "/library.db"
    end
    local cmd = "photo-workflow training collect-corrections --json-progress"
              .. " --photon-db " .. shell_quote(db)
              .. " --folder "    .. shell_quote(folder)
              .. " --darktable-library " .. shell_quote(dt_lib)
    -- Corpus + secondary feedback live on the cartridge (portable) unless overridden.
    local drive = get_drive_root(dest)
    local corpus = config.read("corpus_path")
    if corpus == "" then corpus = drive .. "genre_labels.jsonl" end
    cmd = cmd .. " --corpus " .. shell_quote(corpus)
              .. " --secondary-feedback " .. shell_quote(drive .. "secondary_feedback.jsonl")
    return cmd
  end
  error("Unknown step: " .. step)
end

local function get_log_path(step)
  return get_temp_dir() .. (IS_WINDOWS and "\\" or "/") .. "photonforge_" .. step .. ".log"
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
  if not fh then return false end
  fh:close()
  return true
end

function M.kill()
  M.abort = true
  local pid = read_pid_file()
  if IS_WINDOWS then
    if pid then
      os.execute('taskkill /F /T /PID ' .. pid .. ' >nul 2>&1')
    else
      os.execute('wmic process where "CommandLine like \'%%photo-workflow%%\'" call terminate >nul 2>&1')
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

-- Resolve the shell command for a step without running it. Used by the
-- panel's developer mode to show the exact CLI invocation. Never throws.
function M.preview_cmd(step)
  if step == "import" then
    return "(handled in-process via dt.database.import — no shell command)"
  end
  local ok, cmd = pcall(build_cmd, step)
  if ok then return cmd end
  return "(could not resolve: " .. tostring(cmd) .. ")"
end

-- ---------------------------------------------------------------------------
-- Cartridge management (provision / archive / restore)
--
-- These launch external, often-elevated commands in their own visible window
-- so the user can watch progress (and approve UAC/polkit). They do NOT use the
-- run_step polling loop — they fire-and-forget into a terminal.
-- ---------------------------------------------------------------------------

-- photo-cartridge currently implements only `init`; the provision/archive/
-- restore subcommands these buttons invoke do not exist yet. Flip to true
-- once they are implemented — until then the buttons refuse loudly instead
-- of opening a terminal that dies with "No such command" (or worse, running
-- an elevated command against a mis-resolved drive root).
local CARTRIDGE_CMDS_IMPLEMENTED = false

local function cartridge_cmd_unavailable(name, log_fn)
  if CARTRIDGE_CMDS_IMPLEMENTED then return false end
  log_fn(string.format("[%s] photo-cartridge %s is not implemented yet.", name, name))
  dt.print("PHOTONForge: cartridge " .. name .. " is not available yet")
  return true
end

-- Launch the Cartridge Manager as a SEPARATE, ELEVATED executable. Provisioning
-- sets the volume label (admin/root). The destination drive root is the cartridge.
function M.launch_provision(log_fn)
  if cartridge_cmd_unavailable("provision", log_fn) then return end
  local dest = config.read("dest_path")
  local drive = get_drive_root(dest)
  local id = config.read("cartridge_id")
  local idflag = (id ~= "" and (" --id " .. id)) or ""
  local inner = 'photo-cartridge provision ' .. shell_quote(drive) .. idflag
  log_fn(string.format("[%s] Provisioning cartridge (elevated): %s", os.date("%H:%M:%S"), inner))
  if IS_WINDOWS then
    -- UAC prompt -> elevated cmd window that stays open (/k) showing the result.
    local ps = 'Start-Process cmd -Verb RunAs -ArgumentList \'/k\',\'' .. inner .. '\''
    os.execute('powershell -NoProfile -Command "' .. ps .. '"')
  else
    -- pkexec triggers the polkit prompt; run in a terminal so output is visible.
    os.execute('x-terminal-emulator -e "pkexec ' .. inner .. '" || pkexec ' .. inner .. ' &')
  end
  log_fn("[provision] Launched. Approve the elevation prompt; the cartridge window shows progress.")
end

-- Launch a long-running cartridge command in its own visible terminal window so the
-- user can watch progress (backups can take a long time). elevated=true wraps it in
-- the OS privilege prompt (needed when the command sets a volume label).
local function launch_terminal(inner, elevated)
  if IS_WINDOWS then
    if elevated then
      local ps = 'Start-Process cmd -Verb RunAs -ArgumentList \'/k\',\'' .. inner .. '\''
      os.execute('powershell -NoProfile -Command "' .. ps .. '"')
    else
      os.execute('start "PHOTONForge" cmd /k ' .. inner)
    end
  else
    local cmd = elevated and ('pkexec ' .. inner) or inner
    os.execute('x-terminal-emulator -e "' .. cmd .. '" || ' .. cmd .. ' &')
  end
end

local function backup_flags()
  local repo = config.read("backup_repo")
  local pw = config.read("backup_pwfile")
  if repo == "" then return nil end
  local f = " -r " .. shell_quote(repo)
  if pw ~= "" then f = f .. " --password-file " .. shell_quote(pw) end
  return f
end

-- Archive the whole cartridge (DB + photos) to the configured restic repo.
function M.launch_archive(log_fn)
  if cartridge_cmd_unavailable("archive", log_fn) then return end
  local flags = backup_flags()
  if not flags then
    log_fn("[archive] Set 'Backup repo' in PHOTONForge preferences first.")
    dt.print("PHOTONForge: set a Backup repo in preferences")
    return
  end
  local drive = get_drive_root(config.read("dest_path"))
  local inner = "photo-cartridge archive " .. shell_quote(drive) .. flags .. " --init"
  log_fn(string.format("[%s] Archiving cartridge: %s", os.date("%H:%M:%S"), inner))
  launch_terminal(inner, false)
  log_fn("[archive] Launched in a terminal window; first backup uploads everything, later ones are incremental.")
end

-- Restore an archived cartridge onto the destination drive (DB + photos).
function M.launch_restore(log_fn)
  if cartridge_cmd_unavailable("restore", log_fn) then return end
  local flags = backup_flags()
  if not flags then
    log_fn("[restore] Set 'Backup repo' in PHOTONForge preferences first.")
    dt.print("PHOTONForge: set a Backup repo in preferences")
    return
  end
  local drive = get_drive_root(config.read("dest_path"))
  local id = config.read("cartridge_id")
  local idflag = (id ~= "" and (" --id " .. id)) or ""
  local inner = "photo-cartridge restore" .. flags .. " --to " .. shell_quote(drive) .. idflag
  log_fn(string.format("[%s] Restoring cartridge (elevated): %s", os.date("%H:%M:%S"), inner))
  launch_terminal(inner, true)
  log_fn("[restore] Launched. Approve the elevation prompt; the window shows restore progress.")
end

function M.run_import(log_fn, job)
  local dest = config.read("dest_path")
  log_fn(string.format("[%s] Importing %s into Darktable library...", os.date("%H:%M:%S"), dest))
  local result = dt.database.import(dest)
  if result then
    log_fn(string.format("[%s] Library imported: %s", os.date("%H:%M:%S"), dest))
  else
    log_fn(string.format("[%s] Could not import folder: %s", os.date("%H:%M:%S"), dest))
  end
  return true
end

function M.run_step(step, log_fn, job, progress_fn)
  -- Clear any stale abort from a previously-stopped run. Without this, a
  -- standalone button (Suggest / Refresh / Sync) pressed after a Stop would
  -- immediately short-circuit on the leftover M.abort=true. (run_all checks
  -- M.abort between steps *before* the next run_step, so this reset is safe there.)
  M.abort = false
  if step == "import" then
    return M.run_import(log_fn, job)
  end

  local cmd = build_cmd(step)
  local log_path = get_log_path(step)
  local sentinel = get_sentinel_path()
  log_fn(string.format("[%s] Running: %s", os.date("%H:%M:%S"), cmd))

  local f = io.open(log_path, "w")
  if f then f:close() end

  local sf = io.open(sentinel, "w")
  if sf then sf:write("running\n") sf:close() end

  if IS_WINDOWS then
    local bat_path = get_temp_dir() .. "\\photonforge_" .. step .. ".bat"
    local vbs_path = get_temp_dir() .. "\\photonforge_" .. step .. ".vbs"

    local bat = io.open(bat_path, "w")
    if bat then
      bat:write('@echo off\r\n')
      bat:write(cmd .. ' > "' .. log_path .. '" 2>&1\r\n')
      bat:write('del "' .. sentinel .. '" 2>nul\r\n')
      bat:close()
    end

    local vbs = io.open(vbs_path, "w")
    if vbs then
      vbs:write('CreateObject("Wscript.Shell").Run """' .. bat_path .. '""", 0, False\r\n')
      vbs:close()
    end

    local p = io.popen('wscript "' .. vbs_path .. '"', "r")
    if p then p:read("*a") p:close() end
  else
    os.execute("(" .. cmd .. " > " .. shell_quote(log_path) .. " 2>&1; rm -f " .. shell_quote(sentinel) .. ") &")
  end

  local dest = config.read("dest_path")
  -- Index the library once (O(1) per-record lookups in the applicator). These
  -- steps don't add images, so the index stays valid for the whole run.
  local index = applicator.build_index()
  local done, total = 0, 0
  local file_count = 0
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
      if M.abort then break end
      local ok, rec = pcall(json.decode, line)
      if ok and type(rec) == "table" then
        if rec.step == "_progress" then
          done  = rec.done  or done
          total = rec.total or total
          if job ~= nil and total > 0 then
            job.percent = done / total
          end
          if progress_fn then
            progress_fn(step, done, total)
          end
        else
          if rec.status ~= "info" then
            file_count = file_count + 1
          end
          local msg = string.format("[%s] %s  %s  [%s]",
            os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
          log_fn(msg)
          applicator.apply(rec, dest, index)
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

  -- Process any remaining output only on clean exit (not after abort)
  local fh = io.open(log_path, "r")
  if fh then
    fh:seek("set", last_pos)
    local remaining = fh:read("*a")
    fh:close()
    if remaining and remaining ~= "" then
      for line in remaining:gmatch("[^\r\n]+") do
        local ok, rec = pcall(json.decode, line)
        if ok and type(rec) == "table" and rec.step ~= "_progress" then
          file_count = file_count + 1
          local msg = string.format("[%s] %s  %s  [%s]",
            os.date("%H:%M:%S"), rec.step or "?", rec.file or "", rec.status or "")
          log_fn(msg)
          applicator.apply(rec, dest, index)
        elseif not ok then
          log_fn(line)
        end
      end
    end
  end

  -- After recalibrate, the labeled candidates are folded into the model; clear
  -- the now-stale photon|train_candidate tags so the next Suggest round is clean.
  if step == "recalibrate" then
    local ok, n = pcall(applicator.clear_train_candidates)
    if ok and n and n > 0 then
      log_fn(string.format("[%s] Cleared %d train-candidate tag(s)", os.date("%H:%M:%S"), n))
    end
  end

  log_fn(string.format("[%s] Step finished (%d items)", os.date("%H:%M:%S"), done))
  return true
end

function M.run_all(step_list, log_fn, status_fn, progress_fn)
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

  local step_stats = {}
  local pipeline_start = os.time()

  for i, step in ipairs(step_list) do
    if M.abort then break end
    log_fn(string.format("--- Step %d/%d: %s ---", i, total_steps, step))

    if status_fn ~= nil then
      status_fn(step, "running", "")
    end
    if progress_fn then
      progress_fn(step, 0, 0)
    end

    local step_start = os.time()
    local step_done, step_total = 0, 0
    local function track_progress(s, done, total)
      step_done = done
      step_total = total
      if progress_fn then
        progress_fn(s .. "  |  Step " .. i .. "/" .. total_steps, done, total)
      end
    end

    local ok = M.run_step(step, log_fn, job, track_progress)
    local elapsed = os.time() - step_start

    step_stats[#step_stats + 1] = {
      name = step,
      ok = ok,
      files = step_done,
      seconds = elapsed,
    }

    local result = ok and "ok" or "error"
    if status_fn ~= nil then
      status_fn(step, result, os.date("%Y-%m-%d %H:%M"), step_done)
    end

    if not ok then
      log_fn("[STOPPED] Step failed: " .. step .. ". Remaining steps skipped.")
      break
    end

    job.percent = i / total_steps
  end

  pcall(function() job.valid = false end)
  pcall(function() job:destroy() end)

  if progress_fn then
    progress_fn("", 0, 0)
  end

  local total_elapsed = os.time() - pipeline_start
  local summary = {}
  table.insert(summary, "")
  table.insert(summary, string.format("=== Summary (%ds) ===", total_elapsed))
  for _, s in ipairs(step_stats) do
    local mark = s.ok and "\u{2713}" or "\u{2717}"
    local files_str = s.files > 0 and string.format("  %d files", s.files) or ""
    table.insert(summary, string.format("  %s %s%s  (%ds)", mark, s.name, files_str, s.seconds))
  end
  table.insert(summary, "")
  log_fn(table.concat(summary, "\n"))
  dt.print(string.format("PHOTONForge complete (%ds)", total_elapsed))
end

return M

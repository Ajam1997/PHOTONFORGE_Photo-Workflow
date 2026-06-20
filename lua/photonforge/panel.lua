-- PHOTONForge Darktable panel — Release-1 redesign (Tier 1: existing features).
--
-- Information architecture follows dev-docs/design/dt-plugin-gui-brief.md and the
-- design hand-off: a shared title bar + collapsible configuration above a two-tab
-- `stack` (Pipeline / Training), a running-state block with a pseudo-progress bar,
-- an activity log, and an optional developer block.
--
-- Visual polish (accent fills, status colors, tab chrome) is applied by the
-- companion GTK3-CSS theme `photonforge.css`, which targets widgets by their
-- `name` attribute. The panel is fully functional and legible WITHOUT the CSS —
-- structure, tabs, the unicode progress bar, and status glyphs work everywhere.
--
-- Cartridge strip and the training-weights inspector are deferred follow-ups
-- (Tier 2/3) — see the design brief.

local dt = require "darktable"
local config = require "photonforge/config"
local runner = require "photonforge/runner"

local M = {}

local LOG_MAX_LINES = 200
local PROGRESS_CELLS = 14
local EM_DASH = "\u{2014}"
local CHECK = "\u{2713}"
local CROSS = "\u{2717}"
local IS_WINDOWS = package.config:sub(1,1) == "\\"

-- ---------------------------------------------------------------------------
-- small helpers
-- ---------------------------------------------------------------------------

local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
end

local function set_name(widget, name)
  -- The `name` attribute may not be re-settable on every darktable build; never
  -- let a styling tweak break the panel.
  pcall(function() widget.name = name end)
end

local function open_in_os(path)
  if IS_WINDOWS then
    os.execute('start "" "' .. path .. '"')
  else
    os.execute('xdg-open "' .. path .. '" >/dev/null 2>&1 &')
  end
end

local function fmt_duration(secs)
  secs = math.floor(secs)
  if secs < 60 then return secs .. "s" end
  local mins = math.floor(secs / 60)
  local hrs = math.floor(mins / 60)
  mins = mins % 60
  if hrs > 0 then return string.format("%dh %dm", hrs, mins) end
  return string.format("%dm %ds", mins, secs % 60)
end

local function browse_folder(entry)
  if IS_WINDOWS then
    local tmp = get_temp_dir()
    local vbs_path = tmp .. "\\photonforge_browse.vbs"
    local result_path = tmp .. "\\photonforge_browse.txt"
    os.remove(result_path)

    local vbs = io.open(vbs_path, "w")
    if vbs then
      vbs:write('Set objShell = CreateObject("Shell.Application")\n')
      vbs:write('Set objFolder = objShell.BrowseForFolder(0, "Select folder", &H0001)\n')
      vbs:write('If Not objFolder Is Nothing Then\n')
      vbs:write('  Set fso = CreateObject("Scripting.FileSystemObject")\n')
      vbs:write('  Set f = fso.CreateTextFile("' .. result_path:gsub("\\", "\\\\") .. '", True)\n')
      vbs:write('  f.WriteLine objFolder.Self.Path\n')
      vbs:write('  f.Close\n')
      vbs:write('End If\n')
      vbs:close()
    end

    os.execute('wscript "' .. vbs_path .. '"')

    local fh = io.open(result_path, "r")
    if fh then
      local line = fh:read("*l")
      fh:close()
      os.remove(result_path)
      if line and line ~= "" then
        entry.text = line
      end
    end
  else
    local handle = io.popen('zenity --file-selection --directory 2>/dev/null')
    if handle then
      local result = handle:read("*l")
      handle:close()
      if result and result ~= "" then
        entry.text = result
      end
    end
  end
end

-- ---------------------------------------------------------------------------
-- panel
-- ---------------------------------------------------------------------------

function M.build()
  local entries = {}

  -- == Title bar ============================================================
  local title_label = dt.new_widget("label") { label = "PHOTONFORGE" }
  set_name(title_label, "pf_title")
  local state_label = dt.new_widget("label") { label = "IDLE", halign = "end" }
  set_name(state_label, "pf_state_idle")
  local title_bar = dt.new_widget("box") {
    orientation = "horizontal", title_label, state_label,
  }

  -- == Configuration (collapsible) =========================================
  local function make_path_row(label_text, config_key, placeholder)
    local lbl = dt.new_widget("label") { label = label_text }
    local entry = dt.new_widget("entry") {
      text = config.read(config_key),
      tooltip = label_text,
      placeholder = placeholder,
    }
    entries[config_key] = entry
    if config_key == "dest_path" then
      set_name(entry, "pf_entry_required")
    end

    local btn = dt.new_widget("button") {
      label = "\u{1F4C1}",
      tooltip = "Browse for folder",
      clicked_callback = function() browse_folder(entry) end,
    }
    set_name(btn, "pf_browse")

    return dt.new_widget("box") {
      orientation = "horizontal", lbl, entry, btn,
    }
  end

  local tz_label = dt.new_widget("label") { label = "TZ offset (hrs):" }
  local tz_entry = dt.new_widget("entry") {
    text = tostring(config.read("tz_offset")),
    tooltip = "Hours to add to EXIF timestamp",
  }
  entries["tz_offset"] = tz_entry
  local tz_box = dt.new_widget("box") {
    orientation = "horizontal", tz_label, tz_entry,
  }

  local config_editor = dt.new_widget("box") {
    orientation = "vertical",
    make_path_row("SD card path:", "sd_path", "ingest only\u{2026}"),
    make_path_row("Destination:",  "dest_path", "required\u{2026}"),
    make_path_row("Corpus JSONL (training only):", "corpus_path", "optional\u{2026}"),
    tz_box,
  }

  local config_summary = dt.new_widget("label") { label = "" }
  set_name(config_summary, "pf_config_summary")

  local config_toggle  -- forward ref for closures below

  -- Destination is the only hard requirement (DB + photos live there). SD card
  -- path is needed by the ingest step only, so it does not gate Run.
  local function is_configured()
    return config.read("dest_path") ~= ""
  end

  local function refresh_config_summary()
    local sd = config.read("sd_path")
    local dest = config.read("dest_path")
    if sd == "" then sd = EM_DASH end
    if dest == "" then dest = EM_DASH end
    config_summary.label = string.format("%s \u{00B7} %s \u{00B7} %s \u{00B7} %s",
      sd, dest, config.read("run_mode"), config.read("file_type"))
  end

  local function set_config_collapsed(collapsed)
    config_editor.visible = not collapsed
    config_summary.visible = collapsed
    if config_toggle then
      config_toggle.label = (collapsed and "\u{25B8}" or "\u{25BE}") .. " CONFIGURATION"
    end
  end

  config_toggle = dt.new_widget("button") {
    label = "\u{25BE} CONFIGURATION",
    tooltip = "Show/hide ingest paths and options",
    clicked_callback = function()
      set_config_collapsed(config_editor.visible)
    end,
  }
  set_name(config_toggle, "pf_section")

  local config_section = dt.new_widget("box") {
    orientation = "vertical", config_toggle, config_summary, config_editor,
  }

  -- == Run mode / file type (Pipeline tab) =================================
  local run_modes = {"resume", "force", "fresh"}
  local current_mode = config.read("run_mode")
  local mode_idx = 1
  for i, m in ipairs(run_modes) do if m == current_mode then mode_idx = i end end
  local mode_combo = dt.new_widget("combobox") {
    label = "Run mode",
    tooltip = "resume = skip done steps, force = redo all, fresh = force + re-ingest",
    value = mode_idx, "resume", "force", "fresh",
  }

  local file_types = {"both", "raw", "jpg"}
  local current_ft = config.read("file_type")
  local ft_idx = 1
  for i, ft in ipairs(file_types) do if ft == current_ft then ft_idx = i end end
  local ft_combo = dt.new_widget("combobox") {
    label = "File type",
    tooltip = "raw = ARW/CR2/NEF/DNG only, jpg = JPEG/PNG/TIFF only, both = all",
    value = ft_idx, "both", "raw", "jpg",
  }

  local opts_box = dt.new_widget("box") {
    orientation = "horizontal", mode_combo, ft_combo,
  }

  -- == Pipeline step rows ==================================================
  -- ingest/import run once per photo set; the rest are repeatable.
  local steps = {"ingest", "import", "dedup", "score", "name"}
  local run_once = { ingest = true, import = true }
  local step_checks = {}
  local last_run_labels = {}
  local dev_timing_labels = {}
  local step_start_times = {}

  local steps_box = dt.new_widget("box") { orientation = "vertical" }

  for _, step in ipairs(steps) do
    local check = dt.new_widget("check_button") {
      label = step,
      value = config.read("step_" .. step),
      tooltip = (run_once[step]
        and "Run once per photo set (off by default)"
        or  "Enable " .. step .. " step"),
    }

    local once_lbl = run_once[step]
        and dt.new_widget("label") { label = "ONCE" } or nil
    if once_lbl then set_name(once_lbl, "pf_once") end

    local stored = config.read("last_run_" .. step)
    local last_lbl = dt.new_widget("label") {
      label = (stored ~= "" and stored or EM_DASH), halign = "end",
    }
    step_checks[step] = check
    last_run_labels[step] = last_lbl

    local row_children = { orientation = "horizontal", check }
    if once_lbl then row_children[#row_children + 1] = once_lbl end
    row_children[#row_children + 1] = last_lbl
    steps_box[#steps_box + 1] = dt.new_widget("box")(row_children)
  end

  -- == Running-state block (Pipeline tab) ==================================
  local progress_step_label = dt.new_widget("label") { label = "" }
  set_name(progress_step_label, "pf_progress_step")
  local progress_bar_label = dt.new_widget("label") {
    label = string.rep("\u{2591}", PROGRESS_CELLS),
  }
  set_name(progress_bar_label, "pf_progress_bar")
  local timing_label = dt.new_widget("label") { label = "" }
  set_name(timing_label, "pf_progress_time")

  local running_box = dt.new_widget("box") {
    orientation = "vertical",
    progress_step_label, progress_bar_label, timing_label,
  }
  running_box.visible = false

  local run_start = 0

  -- == Activity log ========================================================
  local log_section = dt.new_widget("section_label") { label = "ACTIVITY LOG" }
  set_name(log_section, "pf_section")
  local log_lines = {}
  local log_view = dt.new_widget("text_view") { editable = false, text = "" }
  set_name(log_view, "pf_log")

  local function append_log(msg)
    table.insert(log_lines, msg)
    if #log_lines > LOG_MAX_LINES then table.remove(log_lines, 1) end
    log_view.text = table.concat(log_lines, "\n")
  end

  -- == Shared state helpers ================================================
  local run_btn, stop_btn  -- forward refs
  local cartridge_btns = {}  -- disabled mid-run

  local function update_state_label()
    local dev = config.read("dev_mode") and " \u{00B7} DEV" or ""
    if running_box.visible then
      state_label.label = "RUNNING" .. dev
      set_name(state_label, "pf_state_running")
    elseif not is_configured() then
      state_label.label = "SETUP" .. dev
      set_name(state_label, "pf_state_setup")
    else
      state_label.label = "IDLE" .. dev
      set_name(state_label, "pf_state_idle")
    end
  end

  -- Maroon "required" border on the mandatory Destination entry — cleared once a
  -- value is present. Reads live entry text (updates on save / action, not keystroke).
  local function refresh_required_marks()
    local e = entries["dest_path"]
    if e then set_name(e, e.text == "" and "pf_entry_required" or "pf_entry_set") end
  end

  local function refresh_run_enabled()
    local ok = is_configured()
    refresh_required_marks()
    if run_btn then
      run_btn.sensitive = ok and not running_box.visible
      run_btn.label = ok and "\u{25B6} Run PHOTONForge" or "\u{25B6} Run \u{2014} set paths first"
    end
    update_state_label()
  end

  local function set_running(on)
    running_box.visible = on
    if on then run_start = os.time() end
    if stop_btn then stop_btn.sensitive = on end
    for _, b in ipairs(cartridge_btns) do b.sensitive = not on end
    refresh_run_enabled()
  end

  local function save_entries()
    for key, w in pairs(entries) do
      if key == "tz_offset" then
        config.write(key, tonumber(w.text) or 0)
      else
        config.write(key, w.text)
      end
    end
    local mv = mode_combo.value
    config.write("run_mode", type(mv) == "number" and (run_modes[mv] or "resume") or tostring(mv))
    local fv = ft_combo.value
    config.write("file_type", type(fv) == "number" and (file_types[fv] or "both") or tostring(fv))
    refresh_config_summary()
  end

  local function update_status(step, result, timestamp, file_count)
    if result == "running" then
      step_start_times[step] = os.time()
      if last_run_labels[step] then last_run_labels[step].label = "Running\u{2026}" end
      return
    end

    -- developer timing (panel-side; works without runner changes)
    if dev_timing_labels[step] and step_start_times[step] then
      local secs = os.time() - step_start_times[step]
      local verb = result == "ok" and "ok" or "FAIL"
      dev_timing_labels[step].label = string.format("%s \u{00B7} %s \u{00B7} %s",
        step, verb, fmt_duration(secs))
      set_name(dev_timing_labels[step], result == "ok" and "pf_step_ok" or "pf_step_fail")
    end

    if last_run_labels[step] == nil then return end
    local mark = result == "ok" and CHECK or CROSS
    local text
    if file_count and file_count > 0 then
      text = string.format("%s %s (%d)", timestamp, mark, file_count)
    else
      text = string.format("%s %s", timestamp, mark)
    end
    last_run_labels[step].label = text
    set_name(last_run_labels[step], result == "ok" and "pf_step_ok" or "pf_step_fail")
    config.write("last_run_" .. step, text)
  end

  local last_log_step = nil

  local function update_progress(step, done, total)
    last_log_step = step:match("^(%S+)") or step
    if not running_box.visible then set_running(true) end

    if total > 0 then
      local filled = math.floor((done / total) * PROGRESS_CELLS + 0.5)
      progress_bar_label.label =
        string.rep("\u{2588}", filled) .. string.rep("\u{2591}", PROGRESS_CELLS - filled)
      progress_step_label.label = string.format("%s  %d/%d", step, done, total)
    else
      progress_bar_label.label = string.rep("\u{2591}", PROGRESS_CELLS)
      progress_step_label.label = step .. "\u{2026}"
    end

    local elapsed = os.time() - run_start
    local eta = EM_DASH
    if done > 0 and total > 0 and elapsed > 0 then
      eta = fmt_duration((total - done) * (elapsed / done))
    end
    timing_label.label = string.format("elapsed %s  \u{00B7}  ETA %s", fmt_duration(elapsed), eta)
  end

  local function clear_progress()
    set_running(false)
    progress_step_label.label = ""
    progress_bar_label.label = string.rep("\u{2591}", PROGRESS_CELLS)
    timing_label.label = ""
  end

  M.update_progress = update_progress
  M.clear_progress = clear_progress

  -- == Action buttons ======================================================
  -- Dispatches a single named step on a background thread with a uniform
  -- log + progress + completion wrapper.
  local function dispatch_step(step, start_msg, done_msg)
    local ok, err = pcall(function()
      save_entries()
      append_log(start_msg)
      dt.control.dispatch(function()
        local ok2, err2 = pcall(runner.run_step, step, append_log, nil, update_progress)
        if not ok2 then
          append_log("[ERROR] " .. step .. ": " .. tostring(err2))
        elseif done_msg then
          append_log(done_msg)
        end
        clear_progress()
      end)
    end)
    if not ok then append_log("[ERROR] " .. tostring(err)) end
  end

  run_btn = dt.new_widget("button") {
    label = "\u{25B6} Run PHOTONForge",
    tooltip = "Run enabled pipeline steps",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        local enabled = {}
        for _, step in ipairs(steps) do
          if step_checks[step].value then
            config.write("step_" .. step, true)
            table.insert(enabled, step)
          else
            config.write("step_" .. step, false)
          end
        end
        if #enabled == 0 then
          append_log("[WARN] No steps enabled.")
          return
        end
        if step_checks["ingest"].value and config.read("sd_path") == "" then
          append_log("[WARN] Ingest is enabled but no SD card path is set. "
                  .. "Set the SD card path or uncheck Ingest.")
          return
        end
        append_log("[RUN] Starting " .. #enabled .. " steps: " .. table.concat(enabled, ", "))
        set_running(true)
        dt.control.dispatch(function()
          local ok2, err2 = pcall(runner.run_all, enabled, append_log, update_status, update_progress)
          if not ok2 then append_log("[ERROR] run_all: " .. tostring(err2)) end
          clear_progress()
        end)
      end)
      if not ok then append_log("[ERROR] " .. tostring(err)) end
    end,
  }
  set_name(run_btn, "pf_run")

  stop_btn = dt.new_widget("button") {
    label = "\u{25A0} Stop",
    tooltip = "Abort current run",
    clicked_callback = function() runner.kill() end,
  }
  set_name(stop_btn, "pf_stop")
  stop_btn.sensitive = false

  local run_row = dt.new_widget("box") {
    orientation = "horizontal", run_btn, stop_btn,
  }

  -- Training / correction-loop actions
  local collect_btn = dt.new_widget("button") {
    label = "1 \u{21C5} Collect Corrections",
    tooltip = "Detect tag corrections made in Darktable and feed them back to the "
           .. "training corpus. Run after reviewing/changing genre tags, then "
           .. "Recalibrate.",
    clicked_callback = function()
      dispatch_step("collect-corrections",
        "[COLLECT] Scanning Darktable tags for corrections...",
        "[COLLECT] Done. Run Recalibrate to apply corrections.")
    end,
  }

  local recalibrate_btn = dt.new_widget("button") {
    label = "2 \u{2605} Recalibrate",
    tooltip = "Recalibrate genre prototypes from the corpus JSONL. Run after "
           .. "Collect Corrections to update training weights.",
    clicked_callback = function()
      dispatch_step("recalibrate",
        "[RECAL] Recalibrating genre prototypes...",
        "[RECAL] Done. Re-score to apply new prototypes.")
    end,
  }

  local sync_tags_btn = dt.new_widget("button") {
    label = "\u{21A5} Sync Tags",
    tooltip = "Push PHOTONForge genre tags from photonforge.db into Darktable "
           .. "(use after scoring from the command line).",
    clicked_callback = function()
      dispatch_step("sync-tags",
        "[SYNC] Pushing genre tags from DB into Darktable...",
        "[SYNC] Done.")
    end,
  }

  local refresh_review_btn = dt.new_widget("button") {
    label = "\u{21BB} Refresh Flags",
    tooltip = "Recompute needs_review from cached embeddings (no re-scoring) and "
           .. "clear stale photon|needs_review tags. Use after a scoring-logic change.",
    clicked_callback = function()
      dispatch_step("refresh-review",
        "[REVIEW] Recomputing needs_review from cached embeddings...",
        "[REVIEW] Done.")
    end,
  }

  local suggest_btn = dt.new_widget("button") {
    label = "\u{2728} Suggest Training Set",
    tooltip = "Pick a small, diverse set of the most useful needs_review frames "
           .. "and tag them photon|train_candidate. Filter to that tag, set the "
           .. "correct subject/type, then Collect Corrections + Recalibrate.",
    clicked_callback = function()
      dispatch_step("suggest-training-set",
        "[SUGGEST] Selecting representative frames to label...",
        "[SUGGEST] Done. Filter by 'photon|train_candidate' and label those frames.")
    end,
  }

  local correction_loop_btn = dt.new_widget("button") {
    label = "\u{21BB} Full Correction Loop",
    tooltip = "Runs the correction feedback loop:\n"
           .. "1. Collect Corrections (harvest DT tag changes, update DB)\n"
           .. "2. Recalibrate (update CLIP prototypes)\n"
           .. "3. Re-score corrected images (ratings only, genres preserved)\n\n"
           .. "Run after reviewing and correcting photon|primary|* tags.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        append_log("[LOOP] Starting full correction loop...")
        set_running(true)
        dt.control.dispatch(function()
          local loop_steps = {"collect-corrections", "recalibrate", "rescore"}
          local ok2, err2 = pcall(runner.run_all, loop_steps, append_log, update_status, update_progress)
          if not ok2 then append_log("[ERROR] correction loop: " .. tostring(err2)) end
          clear_progress()
        end)
      end)
      if not ok then append_log("[ERROR] " .. tostring(err)) end
    end,
  }
  set_name(correction_loop_btn, "pf_run")

  -- == Cartridge strip (shared chrome) =====================================
  -- Provision / Archive / Restore launch external (often elevated) commands in
  -- their own window. Identity/Cartridge ID + Backup repo are set via the
  -- plugin's Lua preferences (darktable Preferences -> Lua options).
  local provision_btn = dt.new_widget("button") {
    label = "\u{1F4BE} Provision",
    tooltip = "Provision the destination drive as a PHOTON cartridge (sets the "
           .. "volume label; needs admin/root). Set the Cartridge ID in the "
           .. "plugin's Lua options first.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        runner.launch_provision(append_log)
      end)
      if not ok then append_log("[ERROR] provision: " .. tostring(err)) end
    end,
  }
  set_name(provision_btn, "pf_cartridge_btn")

  local archive_btn = dt.new_widget("button") {
    label = "\u{2601} Archive",
    tooltip = "Back up the whole cartridge (DB + photos) to the configured restic "
           .. "repo. Set 'Backup repo' in the plugin's Lua options first.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        runner.launch_archive(append_log)
      end)
      if not ok then append_log("[ERROR] archive: " .. tostring(err)) end
    end,
  }
  set_name(archive_btn, "pf_cartridge_btn")

  local restore_btn = dt.new_widget("button") {
    label = "\u{1F504} Restore",
    tooltip = "Restore an archived cartridge (DB + photos) from the backup repo "
           .. "onto the destination drive. Set 'Backup repo' and Cartridge ID first.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        runner.launch_restore(append_log)
      end)
      if not ok then append_log("[ERROR] restore: " .. tostring(err)) end
    end,
  }
  set_name(restore_btn, "pf_cartridge_btn")

  cartridge_btns = { provision_btn, archive_btn, restore_btn }

  local cartridge_strip = dt.new_widget("box") {
    orientation = "vertical",
    dt.new_widget("section_label") { label = "CARTRIDGE" },
    dt.new_widget("box") {
      orientation = "horizontal", provision_btn, archive_btn, restore_btn,
    },
  }
  set_name(cartridge_strip, "pf_cartridge")

  -- == Developer block (optional) ==========================================
  local dev_section = dt.new_widget("section_label") { label = "DEVELOPER" }
  set_name(dev_section, "pf_section")

  local dev_cmd_view = dt.new_widget("text_view") {
    editable = false,
    text = "(press \u{2018}Show resolved command\u{2019})",
  }
  set_name(dev_cmd_view, "pf_log")

  local dev_step_combo = dt.new_widget("combobox") {
    label = "Preview step", value = 3,
    "ingest", "import", "dedup", "score", "name",
    "sync-tags", "suggest-training-set", "refresh-review",
    "recalibrate", "rescore", "collect-corrections",
  }

  local dev_show_btn = dt.new_widget("button") {
    label = "Show resolved command",
    tooltip = "Resolve the exact CLI invocation for the selected step (does not run it)",
    clicked_callback = function()
      save_entries()
      local v = dev_step_combo.value
      local step = type(v) == "number" and dev_step_combo[v] or tostring(v)
      dev_cmd_view.text = runner.preview_cmd(step)
    end,
  }

  local dev_log_btn = dt.new_widget("button") {
    label = "Open log file",
    tooltip = "Open the most recent step log in the system viewer",
    clicked_callback = function()
      local step = last_log_step or "score"
      local sep = IS_WINDOWS and "\\" or "/"
      local path = get_temp_dir() .. sep .. "photonforge_" .. step .. ".log"
      if io.open(path, "r") then
        open_in_os(path)
      else
        open_in_os(get_temp_dir())
      end
    end,
  }

  local dev_timing_box = dt.new_widget("box") { orientation = "vertical" }
  for _, step in ipairs(steps) do
    local lbl = dt.new_widget("label") { label = step .. " \u{00B7} \u{2014}" }
    dev_timing_labels[step] = lbl
    dev_timing_box[#dev_timing_box + 1] = lbl
  end

  local dev_box = dt.new_widget("box") {
    orientation = "vertical",
    dev_section,
    dev_step_combo,
    dev_show_btn,
    dev_cmd_view,
    dt.new_widget("section_label") { label = "LAST RUN \u{00B7} TIMING" },
    dev_timing_box,
    dev_log_btn,
  }
  dev_box.visible = config.read("dev_mode")

  -- == Tabs (stack) ========================================================
  local pipeline_tab = dt.new_widget("box") {
    orientation = "vertical",
    dt.new_widget("section_label") { label = "PIPELINE STEPS" },
    steps_box,
    opts_box,
    run_row,
    running_box,
  }

  local training_tab = dt.new_widget("box") {
    orientation = "vertical",
    dt.new_widget("section_label") { label = "CORRECTION LOOP" },
    dt.new_widget("label") {
      label = "Review genre tags in Darktable, then harvest\nthem back here, or run the full loop.",
    },
    collect_btn,
    recalibrate_btn,
    dt.new_widget("box") { orientation = "horizontal", sync_tags_btn, refresh_review_btn },
    suggest_btn,
    correction_loop_btn,
  }

  local tab_stack = dt.new_widget("stack") { pipeline_tab, training_tab }
  tab_stack.active = pipeline_tab

  local tab_pipeline_btn, tab_training_btn  -- forward refs
  local function set_tab(idx)
    tab_stack.active = (idx == 1) and pipeline_tab or training_tab
    tab_pipeline_btn.label = (idx == 1 and "\u{25CF} " or "\u{25CB} ") .. "Pipeline"
    tab_training_btn.label = (idx == 2 and "\u{25CF} " or "\u{25CB} ") .. "Training"
    set_name(tab_pipeline_btn, idx == 1 and "pf_tab_active" or "pf_tab_idle")
    set_name(tab_training_btn, idx == 2 and "pf_tab_active" or "pf_tab_idle")
  end

  tab_pipeline_btn = dt.new_widget("button") {
    label = "\u{25CF} Pipeline",
    clicked_callback = function() set_tab(1) end,
  }
  tab_training_btn = dt.new_widget("button") {
    label = "\u{25CB} Training",
    clicked_callback = function() set_tab(2) end,
  }
  set_name(tab_pipeline_btn, "pf_tab_active")
  set_name(tab_training_btn, "pf_tab_idle")

  local tab_switch = dt.new_widget("box") {
    orientation = "horizontal", tab_pipeline_btn, tab_training_btn,
  }

  -- == Root ================================================================
  local root = dt.new_widget("box") {
    orientation = "vertical",
    title_bar,
    cartridge_strip,
    config_section,
    tab_switch,
    tab_stack,
    dev_box,
    log_section,
    log_view,
  }

  -- initial state
  refresh_config_summary()
  set_config_collapsed(is_configured())
  refresh_run_enabled()

  M.widget = root
  return root
end

return M

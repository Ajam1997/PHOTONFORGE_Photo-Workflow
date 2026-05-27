local dt = require "darktable"
local config = require "photonforge/config"
local runner = require "photonforge/runner"

local M = {}

local LOG_MAX_LINES = 200
local IS_WINDOWS = package.config:sub(1,1) == "\\"

local function get_temp_dir()
  if IS_WINDOWS then
    return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
  end
  return os.getenv("TMPDIR") or "/tmp"
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

function M.build()
  local entries = {}

  local function make_path_row(label_text, config_key)
    local lbl = dt.new_widget("label") { label = label_text }
    local entry = dt.new_widget("entry") {
      text = config.read(config_key),
      tooltip = label_text,
    }
    entries[config_key] = entry

    local btn = dt.new_widget("button") {
      label = "...",
      tooltip = "Browse for folder",
      clicked_callback = function()
        browse_folder(entry)
      end,
    }

    return dt.new_widget("box") {
      orientation = "horizontal",
      lbl, entry, btn,
    }
  end

  local config_box = dt.new_widget("box") {
    orientation = "vertical",
    make_path_row("SD card path:",  "sd_path"),
    make_path_row("Destination:",   "dest_path"),
    make_path_row("Corpus JSONL:",  "corpus_path"),
  }

  local tz_label = dt.new_widget("label") { label = "TZ offset (hrs):" }
  local tz_entry = dt.new_widget("entry") {
    text = tostring(config.read("tz_offset")),
    tooltip = "Hours to add to EXIF timestamp",
  }
  entries["tz_offset"] = tz_entry
  local tz_box = dt.new_widget("box") {
    orientation = "horizontal", tz_label, tz_entry,
  }

  local run_modes = {"resume", "force", "fresh"}
  local current_mode = config.read("run_mode")
  local mode_idx = 1
  for i, m in ipairs(run_modes) do
    if m == current_mode then mode_idx = i end
  end
  local mode_label = dt.new_widget("label") { label = "Run mode:" }
  local mode_combo = dt.new_widget("combobox") {
    label = "",
    tooltip = "resume = skip done steps, force = redo all, fresh = force + re-ingest",
    value = mode_idx,
    "resume", "force", "fresh",
  }
  local mode_box = dt.new_widget("box") {
    orientation = "horizontal", mode_label, mode_combo,
  }

  local file_types = {"both", "raw", "jpg"}
  local current_ft = config.read("file_type")
  local ft_idx = 1
  for i, ft in ipairs(file_types) do
    if ft == current_ft then ft_idx = i end
  end
  local ft_label = dt.new_widget("label") { label = "File type:" }
  local ft_combo = dt.new_widget("combobox") {
    label = "",
    tooltip = "raw = ARW/CR2/NEF/DNG only, jpg = JPEG/PNG/TIFF only, both = all",
    value = ft_idx,
    "both", "raw", "jpg",
  }
  local ft_box = dt.new_widget("box") {
    orientation = "horizontal", ft_label, ft_combo,
  }

  local function save_entries()
    for key, w in pairs(entries) do
      if key == "tz_offset" then
        config.write(key, tonumber(w.text) or 0)
      else
        config.write(key, w.text)
      end
    end
    local mv = mode_combo.value
    if type(mv) == "number" then
      config.write("run_mode", run_modes[mv] or "resume")
    else
      config.write("run_mode", tostring(mv))
    end
    local fv = ft_combo.value
    if type(fv) == "number" then
      config.write("file_type", file_types[fv] or "both")
    else
      config.write("file_type", tostring(fv))
    end
  end

  local steps = {"ingest", "import", "dedup", "score", "name"}
  local step_checks = {}
  local last_run_labels = {}

  local steps_box = dt.new_widget("box") { orientation = "vertical" }

  for _, step in ipairs(steps) do
    local check = dt.new_widget("check_button") {
      label = step,
      value = config.read("step_" .. step),
      tooltip = "Enable " .. step .. " step",
    }
    local last_lbl = dt.new_widget("label") {
      label = "last: " .. (config.read("last_run_" .. step) ~= "" and config.read("last_run_" .. step) or "\u{2014}"),
    }
    step_checks[step] = check
    last_run_labels[step] = last_lbl

    local row = dt.new_widget("box") {
      orientation = "horizontal", check, last_lbl,
    }
    steps_box[#steps_box + 1] = row
  end

  local log_lines = {}
  local log_view = dt.new_widget("text_view") {
    editable = false,
    text = "",
  }

  local function append_log(msg)
    table.insert(log_lines, msg)
    if #log_lines > LOG_MAX_LINES then
      table.remove(log_lines, 1)
    end
    log_view.text = table.concat(log_lines, "\n")
  end

  local function update_status(step, result, timestamp, file_count)
    -- Steps outside the main pipeline (recalibrate, rescore, etc.) have no
    -- last_run_label widget — silently skip them.
    if last_run_labels[step] == nil then return end
    if result == "running" then
      last_run_labels[step].label = "Running..."
      return
    end
    local mark = result == "ok" and "\u{2713}" or "\u{2717}"
    local text
    if file_count and file_count > 0 then
      text = string.format("%s %s (%d files)", timestamp, mark, file_count)
    else
      text = string.format("%s %s", timestamp, mark)
    end
    last_run_labels[step].label = text
    config.write("last_run_" .. step, text)
  end

  local stop_btn = dt.new_widget("button") {
    label = "\u{25A0} Stop",
    tooltip = "Abort current run",
    clicked_callback = function()
      runner.kill()
    end,
  }

  local sync_tags_btn = dt.new_widget("button") {
    label = "\u{21A5} Sync Tags \u{2192} DT",
    tooltip = "Push PHOTONForge genre tags from photonforge.db into Darktable "
           .. "(use after scoring from the command line)",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        append_log("[SYNC] Pushing genre tags from DB into Darktable...")
        dt.control.dispatch(function()
          local ok2, err2 = pcall(runner.run_step, "sync-tags", append_log, nil, update_progress)
          if not ok2 then
            append_log("[ERROR] sync-tags: " .. tostring(err2))
          else
            append_log("[SYNC] Done.")
          end
          clear_progress()
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
    end,
  }

  local collect_btn = dt.new_widget("button") {
    label = "\u{21C5} Collect Corrections",
    tooltip = "Detect tag corrections made in Darktable and feed them back to "
           .. "the training corpus.  Run after reviewing/changing genre tags in "
           .. "Darktable, then run 'training recalibrate' to update prototypes.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        append_log("[COLLECT] Scanning Darktable tags for corrections...")
        dt.control.dispatch(function()
          local ok2, err2 = pcall(runner.run_step, "collect-corrections", append_log, nil, update_progress)
          if not ok2 then
            append_log("[ERROR] collect-corrections: " .. tostring(err2))
          else
            append_log("[COLLECT] Done. Run 'training recalibrate' to apply corrections.")
          end
          clear_progress()
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
    end,
  }

  local run_btn = dt.new_widget("button") {
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

        append_log("[RUN] Starting " .. #enabled .. " steps: " .. table.concat(enabled, ", "))
        dt.control.dispatch(function()
          local ok2, err2 = pcall(runner.run_all, enabled, append_log, update_status, update_progress)
          if not ok2 then
            append_log("[ERROR] run_all: " .. tostring(err2))
          end
          clear_progress()
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
    end,
  }

  local recalibrate_btn = dt.new_widget("button") {
    label = "\u{2605} Recalibrate",
    tooltip = "Recalibrate genre prototypes from the corpus JSONL. "
           .. "Run after collect-corrections to update training weights.",
    clicked_callback = function()
      local ok, err = pcall(function()
        save_entries()
        append_log("[RECAL] Recalibrating genre prototypes...")
        dt.control.dispatch(function()
          local ok2, err2 = pcall(runner.run_step, "recalibrate", append_log, nil, nil)
          if not ok2 then
            append_log("[ERROR] recalibrate: " .. tostring(err2))
          else
            append_log("[RECAL] Done. Re-score to apply new prototypes.")
          end
          clear_progress()
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
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
        dt.control.dispatch(function()
          local steps = {"collect-corrections", "recalibrate", "rescore"}
          local ok2, err2 = pcall(runner.run_all, steps, append_log, update_status, update_progress)
          if not ok2 then
            append_log("[ERROR] correction loop: " .. tostring(err2))
          end
          clear_progress()
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
    end,
  }

  local btn_box = dt.new_widget("box") {
    orientation = "vertical",
    dt.new_widget("box") { orientation = "horizontal", run_btn, stop_btn },
    sync_tags_btn,
    collect_btn,
    dt.new_widget("box") { orientation = "horizontal", recalibrate_btn, correction_loop_btn },
  }

  local progress_label = dt.new_widget("label") {
    label = "",
  }

  local function update_progress(step, done, total)
    if total > 0 then
      progress_label.label = string.format("%s: %d/%d", step, done, total)
    else
      progress_label.label = step .. "..."
    end
  end

  local function clear_progress()
    progress_label.label = ""
  end

  M.update_progress = update_progress
  M.clear_progress = clear_progress

  local root = dt.new_widget("box") {
    orientation = "vertical",
    config_box,
    tz_box,
    mode_box,
    ft_box,
    steps_box,
    btn_box,
    progress_label,
    log_view,
  }

  M.widget = root
  return root
end

return M

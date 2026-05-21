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
    tooltip = "resume = skip done steps, force = redo all, fresh = delete DB first",
    value = mode_idx,
    "resume", "force", "fresh",
  }
  local mode_box = dt.new_widget("box") {
    orientation = "horizontal", mode_label, mode_combo,
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
  end

  local steps = {"ingest", "scan", "dedup", "score", "name"}
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

  local function update_status(step, result, timestamp)
    local mark = result == "ok" and "\u{2713}" or "\u{2717}"
    local text = string.format("last: %s %s", timestamp, mark)
    last_run_labels[step].label = text
    config.write("last_run_" .. step, timestamp .. " " .. mark)
  end

  local stop_btn = dt.new_widget("button") {
    label = "\u{25A0} Stop",
    tooltip = "Abort current run",
    clicked_callback = function()
      runner.kill()
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
          local ok2, err2 = pcall(runner.run_all, enabled, append_log, update_status)
          if not ok2 then
            append_log("[ERROR] run_all: " .. tostring(err2))
          end
        end)
      end)
      if not ok then
        append_log("[ERROR] " .. tostring(err))
      end
    end,
  }

  local btn_box = dt.new_widget("box") {
    orientation = "horizontal", run_btn, stop_btn,
  }

  local root = dt.new_widget("box") {
    orientation = "vertical",
    config_box,
    tz_box,
    mode_box,
    steps_box,
    btn_box,
    log_view,
  }

  M.widget = root
  return root
end

return M

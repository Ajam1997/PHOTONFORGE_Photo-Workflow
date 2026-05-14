local dt = require "darktable"
local config = require "photonforge/config"
local runner = require "photonforge/runner"

local M = {}

local LOG_MAX_LINES = 200

function M.build()
  local function make_path_entry(label_text, config_key)
    local lbl = dt.new_widget("label") { label = label_text }
    local entry = dt.new_widget("entry") {
      text = config.read(config_key),
      tooltip = label_text,
      changed_callback = function(w)
        config.write(config_key, w.text)
      end,
    }
    return dt.new_widget("box") {
      orientation = "horizontal",
      lbl, entry,
    }
  end

  local config_box = dt.new_widget("box") {
    orientation = "vertical",
    make_path_entry("SD card path:",  "sd_path"),
    make_path_entry("Destination:",   "dest_path"),
    make_path_entry("Model dir:",     "model_dir"),
    make_path_entry("Manifest:",      "manifest"),
  }

  local tz_label = dt.new_widget("label") { label = "TZ offset (hrs):" }
  local tz_entry = dt.new_widget("entry") {
    text = tostring(config.read("tz_offset")),
    tooltip = "Hours to add to EXIF timestamp",
    changed_callback = function(w)
      local n = tonumber(w.text) or 0
      config.write("tz_offset", n)
    end,
  }
  local tz_box = dt.new_widget("box") {
    orientation = "horizontal", tz_label, tz_entry,
  }

  local steps = {"ingest", "dedup", "score", "name", "sync"}
  local step_checks = {}
  local last_run_labels = {}

  local steps_box = dt.new_widget("box") { orientation = "vertical" }

  for _, step in ipairs(steps) do
    local check = dt.new_widget("check_button") {
      label = step,
      value = config.read("step_" .. step),
      tooltip = "Enable " .. step .. " step",
      clicked_callback = function(w)
        config.write("step_" .. step, w.value)
      end,
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
      runner.abort = true
    end,
  }

  local run_btn = dt.new_widget("button") {
    label = "\u{25B6} Run PHOTONForge",
    tooltip = "Run enabled pipeline steps",
    clicked_callback = function()
      local enabled = {}
      for _, step in ipairs(steps) do
        if config.read("step_" .. step) then
          table.insert(enabled, step)
        end
      end
      if #enabled == 0 then
        append_log("[WARN] No steps enabled.")
        return
      end

      dt.control.dispatch(function()
        runner.run_all(enabled, append_log, update_status)
      end)
    end,
  }

  local btn_box = dt.new_widget("box") {
    orientation = "horizontal", run_btn, stop_btn,
  }

  local root = dt.new_widget("box") {
    orientation = "vertical",
    config_box,
    tz_box,
    steps_box,
    btn_box,
    log_view,
  }

  M.widget = root
  return root
end

return M

local dt = require "darktable"
local config      = require "photonforge/config"
local panel       = require "photonforge/panel"
local tag_manager = require "photonforge/tag_manager"

-- Tags are created on demand when a genre is actually applied (sync-tags /
-- tag_manager). We intentionally do NOT pre-seed the full tag hierarchy: it
-- created empty tags that went stale across taxonomy changes and cluttered the
-- tag list with "deprecated" names that no image used.

-- Enforce single-tag-per-axis when the user changes selection
local listen_ok, listen_err = pcall(tag_manager.register_selection_listener)
if not listen_ok then
  dt.print_log("PHOTONForge: tag audit listener failed (non-fatal): " .. tostring(listen_err))
end

local widget = panel.build()

dt.register_lib(
  "photonforge",
  "PHOTONForge",
  true,
  false,
  {
    [dt.gui.views.lighttable] = {"DT_UI_CONTAINER_PANEL_LEFT_CENTER", 99},
  },
  widget
)

dt.print_log("PHOTONForge: plugin registered (v2)")
dt.print("PHOTONForge plugin loaded")

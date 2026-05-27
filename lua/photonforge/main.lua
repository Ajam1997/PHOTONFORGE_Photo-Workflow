local dt = require "darktable"
local config      = require "photonforge/config"
local panel       = require "photonforge/panel"
local tags        = require "photonforge/tags"
local tag_manager = require "photonforge/tag_manager"

-- Seed photon|subject|* and photon|type|* tags into the Darktable library
-- so the hierarchy is visible before any image is scored.
local seed_ok, seed_err = pcall(tags.seed_tag_library)
if not seed_ok then
  dt.print_log("PHOTONForge: tag seeding failed (non-fatal): " .. tostring(seed_err))
end

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

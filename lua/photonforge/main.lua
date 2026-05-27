local dt = require "darktable"
local config = require "photonforge/config"
local panel  = require "photonforge/panel"
local tags   = require "photonforge/tags"

-- Seed the full photon|primary|* and photon|secondary|* tag tree into the
-- Darktable library so the hierarchy is visible before any image is scored,
-- and correction detection can query it reliably.
tags.seed_tag_library()

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

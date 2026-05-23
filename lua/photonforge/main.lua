local dt = require "darktable"
local config = require "photonforge/config"
local panel  = require "photonforge/panel"

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

local dt = require "darktable"
local config = require "photonforge/config"
local panel  = require "photonforge/panel"

local widget = panel.build()

dt.gui.libs.register(
  "photonforge",
  "PHOTONForge",
  true,
  function() end,
  widget,
  dt.gui.views.lighttable,
  {"DT_UI_CONTAINER_PANEL_LEFT_CENTER", 99}
)

dt.print_log("PHOTONForge: plugin registered")

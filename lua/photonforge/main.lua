local dt = require "darktable"

if dt.preferences.read("photonforge", "_loaded", "bool") then
  return
end
dt.preferences.register("photonforge", "_loaded", "bool", "", "", false)
dt.preferences.write("photonforge", "_loaded", "bool", true)

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

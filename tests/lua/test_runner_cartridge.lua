-- Load runner.lua against a stubbed darktable and assert the photo-cartridge
-- command strings it builds.
--
-- The failure this guards against is the one that actually shipped: a panel
-- button that opens a terminal and dies with "No such command" or "No such
-- option", because the Lua string and the click CLI drifted apart. Syntax
-- checking cannot catch that; loading the module and reading the command can.
--
-- Run: lua5.4 tests/lua/test_runner_cartridge.lua   (from the repo root)

package.path = "lua/?.lua;" .. package.path

-- ---------------------------------------------------------------------------
-- Stubs
-- ---------------------------------------------------------------------------
local prefs = {}
local printed = {}

local dt_stub = {
  preferences = {
    register = function() end,
    read = function(_, name) return prefs[name] end,
    write = function(_, name, _, value) prefs[name] = value end,
  },
  print = function(msg) printed[#printed + 1] = msg end,
  print_log = function() end,
  new_widget = function() return function() return {} end end,
  configuration = { config_dir = "/home/alex/.config/darktable" },
  database = {},
  gui = {},
  register_event = function() end,
}
package.loaded["darktable"] = dt_stub
package.loaded["photonforge/applicator"] = { apply = function() end }

-- Capture every shelled-out command instead of running it.
local executed = {}
local real_execute = os.execute
os.execute = function(cmd)          -- luacheck: ignore
  executed[#executed + 1] = cmd
  return true
end

local config = require "photonforge/config"
local runner = require "photonforge/runner"

-- ---------------------------------------------------------------------------
-- Tiny assert helpers
-- ---------------------------------------------------------------------------
local failures, checks = 0, 0

local function check(ok, msg)
  checks = checks + 1
  if not ok then
    failures = failures + 1
    io.stderr:write("FAIL: " .. msg .. "\n")
  end
end

local function contains(haystack, needle, msg)
  check(haystack and haystack:find(needle, 1, true) ~= nil,
        (msg or "") .. "\n  expected to find: " .. needle ..
        "\n  in: " .. tostring(haystack))
end

local logged = {}
local function log_fn(m) logged[#logged + 1] = m end

local function reset()
  executed, logged, printed = {}, {}, {}
end

local function last_cmd()
  return executed[#executed]
end

-- ---------------------------------------------------------------------------
-- Fixtures: a Linux cartridge at /media/alex/PHOTON-004
-- ---------------------------------------------------------------------------
prefs.dest_path = "/media/alex/PHOTON-004/ICELAND"
prefs.backup_dest = "/media/alex/BACKUP"
prefs.snapshot_keep = 7
prefs.backup_keep = 10
prefs.cli_path = ""
prefs.cartridge_path = ""
prefs.models_path = ""
prefs.backup_repo = ""
prefs.backup_pwfile = ""
prefs.cartridge_id = "004"

-- === Tier 1: snapshot ======================================================
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge snapshot", "snapshot invokes the subcommand")
contains(last_cmd(), "'/media/alex/PHOTON-004/'", "snapshot targets the cartridge root")
contains(last_cmd(), "--keep 7", "snapshot passes the retention pref")

-- === Tier 2: backup ========================================================
reset()
runner.launch_backup(log_fn)
contains(last_cmd(), "photo-cartridge backup", "backup invokes the subcommand")
contains(last_cmd(), "'/media/alex/PHOTON-004/'", "backup targets the cartridge root")
contains(last_cmd(), "--dest '/media/alex/BACKUP'", "backup passes the destination")
contains(last_cmd(), "--keep 10", "backup passes the retention pref")

-- === Tier 2: verify ========================================================
reset()
runner.launch_verify(log_fn)
contains(last_cmd(), "photo-cartridge verify-backup", "verify invokes the subcommand")
contains(last_cmd(), "--dest '/media/alex/BACKUP'", "verify passes the destination")
contains(last_cmd(), "--root '/media/alex/PHOTON-004/'", "verify scopes to the cartridge")

-- === Gating: unimplemented commands must not shell out =====================
for _, name in ipairs({ "provision", "archive", "restore" }) do
  reset()
  local fn = runner["launch_" .. name]
  check(fn ~= nil, "runner.launch_" .. name .. " exists")
  if fn then fn(log_fn) end
  check(#executed == 0, name .. " must not execute anything while gated off")
  check(#logged > 0, name .. " must say why it refused")
  contains(table.concat(logged, "\n"), "not implemented", name .. " logs the reason")
end

-- === Missing prefs are refused, not silently mis-invoked ===================
prefs.backup_dest = ""
reset()
runner.launch_backup(log_fn)
check(#executed == 0, "backup with no destination must not execute")
contains(table.concat(logged, "\n"), "Backup dest", "backup names the missing pref")

reset()
runner.launch_verify(log_fn)
check(#executed == 0, "verify with no destination must not execute")
prefs.backup_dest = "/media/alex/BACKUP"

-- Snapshot needs no destination — it writes onto the cartridge itself.
reset()
runner.launch_snapshot(log_fn)
check(#executed == 1, "snapshot works without a backup destination")

-- === The CLI must be resolved, not invoked by bare name ====================
-- Darktable launches as a GUI, so its subprocess PATH excludes the venv's
-- Scripts dir. A bare `photo-cartridge` dies with "not recognized" inside the
-- terminal the button just opened -- which is exactly what shipped once.
prefs.cli_path = "F:\\repo\\.venv\\Scripts\\photo-workflow.exe"
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge.exe", "snapshot uses the resolved exe, not the bare name")
contains(last_cmd(), "F:\\repo\\.venv\\Scripts\\", "snapshot keeps the venv directory")
check(last_cmd():find("[^\\\\]photo%-cartridge snapshot") == nil,
      "snapshot must not invoke a bare 'photo-cartridge'")

reset()
runner.launch_backup(log_fn)
contains(last_cmd(), "photo-cartridge.exe", "backup uses the resolved exe")

reset()
runner.launch_verify(log_fn)
contains(last_cmd(), "photo-cartridge.exe", "verify uses the resolved exe")

-- An explicit override wins over the derivation.
prefs.cartridge_path = "D:\\custom\\pc.exe"
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "D:\\custom\\pc.exe", "cartridge_path overrides the derived path")
prefs.cartridge_path = ""

-- Blank cli_path (Linux/container: it really is on PATH) falls back to bare.
prefs.cli_path = ""
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge snapshot", "bare name is the fallback when nothing is configured")

-- === config.read must know every key the runner reads ======================
for _, key in ipairs({ "backup_dest", "snapshot_keep", "backup_keep",
                       "dest_path", "cli_path", "cartridge_path" }) do
  local ok = pcall(config.read, key)
  check(ok, "config.read knows '" .. key .. "'")
end

-- ---------------------------------------------------------------------------
os.execute = real_execute           -- luacheck: ignore
io.write(string.format("%d checks, %d failure(s)\n", checks, failures))
os.exit(failures == 0 and 0 or 1)

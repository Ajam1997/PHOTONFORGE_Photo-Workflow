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

-- cartridge_cli() only honours a path that actually opens as a file, so the
-- resolution tests need real ones. These are created relative to the CWD (the
-- repo root) and removed at the end. On Linux a "F:\\..." string is simply a
-- filename containing backslashes, which is exactly what we want for the
-- Windows-mode section.
local made_files = {}
local function make_fake(path)
  local fh = io.open(path, "w")
  if fh then
    fh:write("x")
    fh:close()
    made_files[#made_files + 1] = path
  end
  return path
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
local fake_wf = make_fake("./photo-workflow.testbin")
make_fake("./photo-cartridge.testbin")
prefs.cli_path = fake_wf
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge.testbin", "snapshot uses the resolved sibling, not the bare name")
check(last_cmd():find("[^%.]photo%-cartridge snapshot") == nil,
      "snapshot must not invoke a bare 'photo-cartridge'")

reset()
runner.launch_backup(log_fn)
contains(last_cmd(), "photo-cartridge.testbin", "backup uses the resolved sibling")

reset()
runner.launch_verify(log_fn)
contains(last_cmd(), "photo-cartridge.testbin", "verify uses the resolved sibling")

-- An explicit override wins over the derivation -- but only if it is a real
-- file. This harness runs from the repo root, so use a file that exists here.
prefs.cartridge_path = "README.md"
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "README.md", "an existing cartridge_path overrides the derivation")

-- A path that is not a file must be IGNORED, not used as the program name.
-- Pointing this preference at the cartridge drive produced
--   "H:\\" backup "H:\\" ...
-- and cmd said '"H:\\"' is not recognized, naming nothing useful.
prefs.cartridge_path = "/definitely/not/a/file"
reset()
runner.launch_snapshot(log_fn)
check(last_cmd():find("/definitely/not/a/file", 1, true) == nil,
      "a non-file cartridge_path must not become the program")
contains(last_cmd(), "photo-cartridge", "it falls back to a real resolution")
contains(table.concat(logged, "\n"), "not a file",
         "and says which preference is wrong")
contains(table.concat(logged, "\n"), "not the cartridge drive",
         "and names the likely mistake")
prefs.cartridge_path = ""

-- A cli_path whose sibling does not exist warns and falls back rather than
-- invoking a path that is not there.
prefs.cli_path = "/nowhere/photo-workflow"
reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge snapshot", "missing sibling falls back to PATH")
contains(table.concat(logged, "\n"), "does not exist", "and says the derived path is missing")

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

-- ===========================================================================
-- Self-location (portable drive)
--
-- The keystone of the portable-drive plan: launched with
-- --configdir <DRIVE>/dt-config, the plugin must resolve the CLI and the models
-- from the CURRENT mount, with no preference set and no absolute path baked in
-- anywhere. Darktable rewrites darktablerc on exit and the drive letter changes
-- between machines, so anything stored would be wrong by the next run.
--
-- Uses a real directory tree, because resolution is existence-based.
-- ===========================================================================
local drive = "./pf_drive_test"
-- real_execute, not os.execute: the latter is stubbed above to capture
-- commands rather than run them, so a mkdir through it would silently do
-- nothing and the probes would all miss.
real_execute("mkdir -p " .. drive .. "/dt-config " .. drive .. "/runtime/linux "
             .. drive .. "/models/florence2_int8")
make_fake(drive .. "/runtime/linux/photo-workflow")
make_fake(drive .. "/runtime/linux/photo-cartridge")

local real_config_dir = dt_stub.configuration.config_dir

-- Nothing configured: exactly the state a freshly built portable drive is in.
prefs.cli_path = ""
prefs.cartridge_path = ""
prefs.models_path = ""
prefs.dest_path = drive .. "/ICELAND"
dt_stub.configuration.config_dir = drive .. "/dt-config"

reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), drive .. "/runtime/linux/photo-cartridge",
         "portable: cartridge CLI resolves from the drive with no pref set")

local preview_ok, preview = pcall(runner.preview_cmd, "score")
check(preview_ok, "portable: preview_cmd must not throw")
contains(preview or "", drive .. "/runtime/linux/photo-workflow",
         "portable: photo-workflow resolves from the drive")
contains(preview or "", "--model-dir",
         "portable: models are passed explicitly")
contains(preview or "", drive .. "/models",
         "portable: models resolve from the drive")

-- An explicit preference still wins -- the portable probe must not hijack a
-- deliberately configured dev install.
prefs.cli_path = fake_wf
reset()
local _, pinned = pcall(runner.preview_cmd, "score")
contains(pinned or "", fake_wf, "portable: a configured cli_path still wins")
prefs.cli_path = ""

-- A host install (config dir with no runtime/ or models/ beside it) must behave
-- exactly as before: bare name, no --model-dir. This is the backward-compatible
-- half of the contract.
dt_stub.configuration.config_dir = "/home/alex/.config/darktable"
reset()
local _, host = pcall(runner.preview_cmd, "score")
contains(host or "", "photo-workflow score", "host install: bare name unchanged")
check((host or ""):find("--model-dir") == nil,
      "host install: no --model-dir when nothing is configured or on the drive")

reset()
runner.launch_snapshot(log_fn)
contains(last_cmd(), "photo-cartridge snapshot",
         "host install: cartridge falls back to the bare name")

-- config_parent() must survive a darktable stub that raises or returns junk;
-- preview_cmd resolves commands without executing them and must never throw.
local saved_conf = dt_stub.configuration
dt_stub.configuration = setmetatable({}, { __index = function() error("boom") end })
local safe_ok = pcall(runner.preview_cmd, "score")
check(safe_ok, "a broken darktable.configuration must not make preview_cmd throw")
dt_stub.configuration = saved_conf

dt_stub.configuration.config_dir = real_config_dir
prefs.dest_path = "/media/alex/PHOTON-004/ICELAND"
real_execute("rm -rf " .. drive)

-- ===========================================================================
-- Windows mode
--
-- Everything above ran with POSIX quoting, but the panel's primary home is
-- Windows -- and Windows is where the quoting actually bites. runner.lua picks
-- its branch from package.config at load time, so swap that and re-require.
--
-- On Windows the command is written to a .bat and cmd runs the file, so the
-- assertions read the batch contents: that is what actually executes.
-- ===========================================================================
package.loaded["photonforge/runner"] = nil
package.loaded["photonforge/config"] = nil
local real_package_config = package.config
package.config = "\\\n;\n?\n!\n-\n"   -- Windows separators
config = require "photonforge/config"
runner = require "photonforge/runner"

local function win_temp()
  return os.getenv("TEMP") or os.getenv("TMP") or "C:\\Temp"
end

local written = {}

local function bat_path(tag)
  return win_temp() .. "\\photonforge_" .. tag .. ".bat"
end

-- The command line inside the batch file (the last non-empty line).
local function bat_command(tag)
  local path = bat_path(tag)
  written[path] = true
  local fh = io.open(path, "r")
  if not fh then return nil end
  local text = fh:read("*a")
  fh:close()
  local last
  for line in text:gmatch("[^\r\n]+") do last = line end
  return last, text
end

prefs.dest_path = "H:\\Photos\\ICELAND"
prefs.cli_path = make_fake("F:\\repo\\.venv\\Scripts\\photo-workflow.exe")
make_fake("F:\\repo\\.venv\\Scripts\\photo-cartridge.exe")
prefs.backup_dest = "G:\\BACKUP"
prefs.cartridge_path = ""

reset()
runner.launch_snapshot(log_fn)

-- cmd /k gets exactly two quotes around a .bat path -- the one shape cmd
-- parses predictably. Nesting the real command there is what failed three
-- times: cmd strips the first and last quote unless there are exactly two.
contains(last_cmd(), 'cmd /k "', "windows: cmd /k runs a quoted batch file")
contains(last_cmd(), "photonforge_snapshot.bat", "windows: per-command batch name")
check(select(2, last_cmd():gsub('"', '')) == 4,
      "windows: the launch line has exactly 4 quotes (title + bat), nothing nested")

local snap_cmd, snap_text = bat_command("snapshot")
check(snap_cmd ~= nil, "windows: snapshot batch file was written")
contains(snap_text or "", "@echo on",
         "windows: batch echoes the command so the window shows what ran")
contains(snap_cmd or "", '"F:\\repo\\.venv\\Scripts\\photo-cartridge.exe"',
         "windows: batch invokes the resolved exe")
contains(snap_cmd or "", '"H:\\\\"',
         "windows: drive root keeps its separator (doubled)")
check((snap_cmd or ""):find('"H:"', 1, true) == nil,
      'windows: drive root must not collapse to "H:" (means cwd on H:, not the root)')
contains(snap_cmd or "", "--keep 7", "windows: snapshot passes retention")

reset()
runner.launch_backup(log_fn)
local backup_cmd = bat_command("backup")
contains(backup_cmd or "", '"H:\\\\"', "windows: backup passes the real drive root")
contains(backup_cmd or "", '--dest "G:\\BACKUP"', "windows: backup destination is quoted")
check((backup_cmd or ""):find('"H:"', 1, true) == nil, "windows: backup root must not collapse")

reset()
runner.launch_verify(log_fn)
local verify_cmd = bat_command("verify")
contains(verify_cmd or "", '--dest "G:\\BACKUP"', "windows: verify quotes the destination")
contains(verify_cmd or "", '--root "H:\\\\"', "windows: verify scopes to the drive root")

for path in pairs(written) do os.remove(path) end
for _, path in ipairs(made_files) do os.remove(path) end

package.config = real_package_config

-- ---------------------------------------------------------------------------
os.execute = real_execute           -- luacheck: ignore
io.write(string.format("%d checks, %d failure(s)\n", checks, failures))
os.exit(failures == 0 and 0 or 1)

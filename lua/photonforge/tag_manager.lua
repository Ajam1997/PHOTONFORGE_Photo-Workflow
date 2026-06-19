local dt = require "darktable"
local M = {}

local SUBJECT_PREFIX = "photon|subject|"
local TYPE_PREFIX    = "photon|type|"

local function detach_axis(image, prefix, keep_name)
  for _, tag in ipairs(dt.tags.get_tags(image)) do
    if tag.name:sub(1, #prefix) == prefix and tag.name ~= keep_name then
      dt.tags.detach(tag, image)
    end
  end
end

function M.attach_subject(image, name)
  local full = SUBJECT_PREFIX .. name
  detach_axis(image, SUBJECT_PREFIX, full)
  local tag = dt.tags.create(full)
  dt.tags.attach(tag, image)
end

function M.attach_type(image, name)
  local full = TYPE_PREFIX .. name
  detach_axis(image, TYPE_PREFIX, full)
  local tag = dt.tags.create(full)
  dt.tags.attach(tag, image)
end

local function collect_axis_tags(image, prefix)
  local found = {}
  for _, tag in ipairs(dt.tags.get_tags(image)) do
    if tag.name:sub(1, #prefix) == prefix then
      found[#found + 1] = tag
    end
  end
  return found
end

local function resolve_conflict(tags)
  -- Keep the last non-"general" tag; fall back to "general" if all are general
  local last_specific = nil
  local last_any = nil
  for _, tag in ipairs(tags) do
    last_any = tag
    local suffix = tag.name:match("|([^|]+)$")
    if suffix ~= "general" then
      last_specific = tag
    end
  end
  return last_specific or last_any
end

function M.audit_image(image)
  local changed = false

  local subj_tags = collect_axis_tags(image, SUBJECT_PREFIX)
  if #subj_tags > 1 then
    local keep = resolve_conflict(subj_tags)
    for _, tag in ipairs(subj_tags) do
      if tag.name ~= keep.name then
        dt.tags.detach(tag, image)
        changed = true
      end
    end
  end

  local type_tags = collect_axis_tags(image, TYPE_PREFIX)
  if #type_tags > 1 then
    local keep = resolve_conflict(type_tags)
    for _, tag in ipairs(type_tags) do
      if tag.name ~= keep.name then
        dt.tags.detach(tag, image)
        changed = true
      end
    end
  end

  return changed
end

function M.register_selection_listener()
  dt.register_event("photonforge_tag_audit", "selection-changed", function(_event)
    local sel = dt.gui.selection()
    if sel == nil then return end
    for _, image in ipairs(sel) do
      local ok, did_change = pcall(M.audit_image, image)
      if ok and did_change then
        dt.print_log(string.format(
          "PHOTONForge: cleaned duplicate axis tags on %s", image.filename))
      end
    end
  end)
end

return M

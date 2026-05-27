local dt = require "darktable"
local M = {}

-- Two-axis genre system: Subject (what) x Photo Type (how)
local SUBJECTS = {
  "person", "people", "child", "wildlife", "pet",
  "plant", "landscape", "seascape", "cityscape", "building",
  "vehicle", "food", "object", "text", "night-sky", "abstract",
}

local PHOTO_TYPES = {
  "portrait", "candid", "landscape", "street", "wildlife",
  "macro", "architecture", "action", "aerial", "long-exposure",
  "still-life", "documentary",
}

local STATIC_TAGS = {
  "photon|needs_review",
}

function M.seed_tag_library()
  local created = 0
  local all_names = {}

  for _, subj in ipairs(SUBJECTS) do
    table.insert(all_names, "photon|subject|" .. subj)
  end

  for _, ptype in ipairs(PHOTO_TYPES) do
    table.insert(all_names, "photon|type|" .. ptype)
  end

  for _, name in ipairs(STATIC_TAGS) do
    table.insert(all_names, name)
  end

  for _, name in ipairs(all_names) do
    local ok, tag = pcall(dt.tags.create, name)
    if ok and tag then
      created = created + 1
    end
  end

  dt.print_log(string.format("PHOTONForge: seeded %d tag(s) into library", created))
end

return M

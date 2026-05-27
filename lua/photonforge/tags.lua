local dt = require "darktable"
local M = {}

-- All genres recognised by the genre router (must match GENRES in genre_router.py)
local GENRES = {
  "wildlife", "landscape", "portrait", "street",
  "architecture", "macro", "event", "waterfall",
  "signage", "cat", "vehicle", "general",
}

-- Full tag tree written to the Darktable tag library on plugin start.
-- Hierarchy uses the pipe separator darktable uses for tag trees:
--   photon|primary|<genre>   — 1st-order (product-of-experts winner)
--   photon|secondary|<genre> — 2nd-order (geometric mean co-genres)
--   photon|needs_review      — router was uncertain; human review requested
--
-- Pre-seeding means the tree is visible in the tag panel before any image
-- is scored, and correction detection can reliably query photon|primary|*
-- and photon|secondary|* without worrying about missing nodes.

local STATIC_TAGS = {
  "photon|needs_review",
}

function M.seed_tag_library()
  local created = 0

  -- Primary and secondary namespaces for every genre
  for _, genre in ipairs(GENRES) do
    local tags = {
      "photon|primary|"   .. genre,
      "photon|secondary|" .. genre,
    }
    for _, name in ipairs(tags) do
      local tag = dt.tags.create(name)
      if tag then created = created + 1 end
    end
  end

  -- Static utility tags
  for _, name in ipairs(STATIC_TAGS) do
    local tag = dt.tags.create(name)
    if tag then created = created + 1 end
  end

  dt.print_log(string.format("PHOTONForge: seeded %d tag(s) into library", created))
end

return M

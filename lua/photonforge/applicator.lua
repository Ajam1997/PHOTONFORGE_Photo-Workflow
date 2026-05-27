local dt = require "darktable"
local M = {}

local function normalize_path(p)
  if p == nil then return "" end
  p = p:gsub("\\", "/")   -- backslash → forward slash
  p = p:gsub("/+$", "")   -- strip trailing slashes
  return p:lower()         -- case-insensitive on Windows
end

local function find_image(filename, folder)
  local norm_folder = normalize_path(folder)
  for _, img in ipairs(dt.database) do
    -- Guard: DT5 database proxies can yield nil-like entries
    if img ~= nil and img.filename == filename
        and normalize_path(img.path) == norm_folder then
      return img
    end
  end
  return nil
end

function M.apply(rec, folder)
  if rec.step == "_progress" then
    return
  end

  if rec.status == "error" then
    dt.print_log(string.format("PHOTONForge error [%s] %s: %s",
      rec.step, rec.file or "?", rec.message or "unknown"))
    return
  end

  if rec.step == "ingest" then
    dt.print_log(string.format("PHOTONForge ingested: %s", rec.file or ""))
    return
  end

  -- sync-tags and collect-corrections write directly to DB from Python;
  -- no Lua action needed for either.
  if rec.step == "sync-tags" or rec.step == "collect-corrections" then
    return
  end

  local img = find_image(rec.file, folder)
  if img == nil then
    dt.print_log(string.format("PHOTONForge: image not found in library: %s", rec.file or ""))
    return
  end

  if rec.step == "dedup" then
    if rec.status == "duplicate" then
      img.rating = 0
      img.red = true
    end

  elseif rec.step == "score" then
    if rec.stars ~= nil then
      img.rating = math.min(5, math.max(0, math.floor(rec.stars + 0.5)))
    end
    local cl = rec.color_label
    if cl ~= nil and cl >= 0 then
      img.red    = (cl == 0)
      img.yellow = (cl == 1)
      img.green  = (cl == 2)
      img.blue   = (cl == 3)
      img.purple = (cl == 4)
    end

    local parts = {}
    if rec.sharpness ~= nil then table.insert(parts, string.format("Sharp:%.2f", rec.sharpness)) end
    if rec.composition ~= nil then table.insert(parts, string.format("Comp:%.2f", rec.composition)) end
    if rec.exposure ~= nil then table.insert(parts, string.format("Expo:%.2f", rec.exposure)) end
    if #parts > 0 then
      img.notes = table.concat(parts, " | ")
    end

    -- Multi-genre tagging (FR-1.7.2, design D5).
    -- Writes hierarchical tags: photon|primary|<genre> for the first entry
    -- (product-of-experts winner) and photon|secondary|<genre> for the rest
    -- (geometric mean co-genres).  Falls back to flat rec.genre for legacy
    -- score payloads that pre-date the genres list.
    if rec.genres ~= nil and #rec.genres > 0 then
      for i, entry in ipairs(rec.genres) do
        if entry.g ~= nil and entry.g ~= "" then
          local prefix = (i == 1) and "photon|primary|" or "photon|secondary|"
          local tag = dt.tags.create(prefix .. entry.g)
          dt.tags.attach(tag, img)
        end
      end
    elseif rec.genre ~= nil and rec.genre ~= "" then
      local tag = dt.tags.create("photon|primary|" .. rec.genre)
      dt.tags.attach(tag, img)
    end

    -- needs_review flag
    if rec.needs_review then
      local tag = dt.tags.create("photon|needs_review")
      dt.tags.attach(tag, img)
    end

    if rec.original_name ~= nil then
      img.PreservedFileName = rec.original_name
    end

  elseif rec.step == "name" then
    if rec.semantic_name ~= nil then
      img.description = rec.semantic_name
    end
  end
end

return M

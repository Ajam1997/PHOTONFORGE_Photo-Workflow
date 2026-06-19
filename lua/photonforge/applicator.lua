local dt = require "darktable"
local tag_manager = require "photonforge/tag_manager"
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

  -- collect-corrections writes directly to DB from Python; no Lua action needed.
  if rec.step == "collect-corrections" then
    return
  end

  -- suggest-training-set: tag the picked frames so the user can filter to a small
  -- labeling set (photon|train_candidate), then label + Collect Corrections.
  if rec.step == "train-candidate" then
    local img = find_image(rec.file, folder)
    if img == nil then
      dt.print_log(string.format("PHOTONForge train-candidate: image not found: %s", rec.file or ""))
      return
    end
    local tag = dt.tags.create("photon|train_candidate")
    dt.tags.attach(tag, img)
    return
  end

  -- sync-tags: apply genre tags via DT API (Python emits subject/photo_type)
  if rec.step == "sync-tags" then
    local img = find_image(rec.file, folder)
    if img == nil then
      dt.print_log(string.format("PHOTONForge sync-tags: image not found: %s", rec.file or ""))
      return
    end
    if rec.subject ~= nil and rec.subject ~= "" then
      tag_manager.attach_subject(img, rec.subject)
    end
    if rec.photo_type ~= nil and rec.photo_type ~= "" then
      tag_manager.attach_type(img, rec.photo_type)
    end
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

    -- Detach stale needs_review before re-scoring
    for _, tag in ipairs(dt.tags.get_tags(img)) do
      if tag.name == "photon|needs_review" then
        dt.tags.detach(tag, img)
      end
    end

    -- Two-axis tagging via tag_manager (auto-detaches old axis tag)
    if rec.subject ~= nil and rec.subject ~= "" then
      tag_manager.attach_subject(img, rec.subject)
    end
    if rec.photo_type ~= nil and rec.photo_type ~= "" then
      tag_manager.attach_type(img, rec.photo_type)
    end

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

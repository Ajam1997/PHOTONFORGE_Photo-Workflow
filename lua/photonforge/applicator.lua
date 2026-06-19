local dt = require "darktable"
local tag_manager = require "photonforge/tag_manager"
local M = {}

local function normalize_path(p)
  if p == nil then return "" end
  p = p:gsub("\\", "/")   -- backslash → forward slash
  p = p:gsub("/+$", "")   -- strip trailing slashes
  return p:lower()         -- case-insensitive on Windows
end

local function _key(filename, folder)
  return normalize_path(folder) .. "|" .. (filename or "")
end

-- Build a {normalized "folder|filename" -> img} index in ONE pass over the
-- library. Per-record lookups against this are O(1); without it each apply
-- linearly scanned the whole library (~seconds each on a large catalog, so a
-- multi-thousand-record step like refresh-review appeared to hang).
function M.build_index()
  local idx = {}
  for _, img in ipairs(dt.database) do
    if img ~= nil and img.filename ~= nil then
      idx[_key(img.filename, img.path)] = img
    end
  end
  return idx
end

-- Detach photon|train_candidate from every image that carries it. Called after
-- Recalibrate: the candidates have been labeled and folded into the model, so the
-- tag is stale and would otherwise linger into the next Suggest round.
function M.clear_train_candidates()
  local t = dt.tags.find("photon|train_candidate")
  if t == nil then return 0 end
  local imgs = {}
  for _, img in ipairs(t) do imgs[#imgs + 1] = img end  -- snapshot before mutating
  for _, img in ipairs(imgs) do dt.tags.detach(t, img) end
  return #imgs
end

local function find_image(filename, folder, index)
  if index ~= nil then
    return index[_key(filename, folder)]
  end
  -- Fallback: linear scan (used only if no index was supplied).
  local norm_folder = normalize_path(folder)
  for _, img in ipairs(dt.database) do
    if img ~= nil and img.filename == filename
        and normalize_path(img.path) == norm_folder then
      return img
    end
  end
  return nil
end

function M.apply(rec, folder, index)
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
    local img = find_image(rec.file, folder, index)
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
    local img = find_image(rec.file, folder, index)
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

  local img = find_image(rec.file, folder, index)
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
    if rec.reject then
      -- Technical failure -> Darktable reject flag (no star/color).
      img.rating = -1
    elseif rec.stars ~= nil then
      img.rating = math.min(5, math.max(0, math.floor(rec.stars + 0.5)))
    end
    if not rec.reject then
      local cl = rec.color_label
      if cl ~= nil and cl >= 0 then
        -- Automatic scoring colors only. PURPLE is reserved as a USER flag
        -- (mark-for-edit/export) and is deliberately never written here, so a
        -- re-score can't wipe a manually-set purple selection.
        img.red    = (cl == 0)
        img.yellow = (cl == 1)
        img.green  = (cl == 2)
        img.blue   = (cl == 3)
      end
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

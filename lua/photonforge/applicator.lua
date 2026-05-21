local dt = require "darktable"
local M = {}

local function find_image(filename, folder)
  for _, img in ipairs(dt.database) do
    if img.filename == filename and img.path == folder then
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

  elseif rec.step == "name" then
    if rec.semantic_name ~= nil then
      img:set_metadata("description", rec.semantic_name)
    end
  end
end

return M

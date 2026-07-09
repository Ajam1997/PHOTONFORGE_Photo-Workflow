local M = {}

-- Sentinel for JSON null: distinguishes "parsed null" from "parse error"
-- (both used to return nil, which silently shifted array elements and made
-- errors ambiguous). Objects drop null-valued keys; arrays keep the sentinel
-- so element positions survive.
M.null = setmetatable({}, { __tostring = function() return "null" end })

local function skip_ws(s, i)
  return s:match("^%s*()", i)
end

local function utf8_encode(cp)
  if cp < 0x80 then
    return string.char(cp)
  elseif cp < 0x800 then
    return string.char(0xC0 + math.floor(cp / 0x40), 0x80 + cp % 0x40)
  elseif cp < 0x10000 then
    return string.char(
      0xE0 + math.floor(cp / 0x1000),
      0x80 + math.floor(cp / 0x40) % 0x40,
      0x80 + cp % 0x40)
  else
    return string.char(
      0xF0 + math.floor(cp / 0x40000),
      0x80 + math.floor(cp / 0x1000) % 0x40,
      0x80 + math.floor(cp / 0x40) % 0x40,
      0x80 + cp % 0x40)
  end
end

local function parse_string(s, i)
  if s:byte(i) ~= 34 then return nil, i end
  local j = i + 1
  local parts = {}
  while j <= #s do
    local c = s:byte(j)
    if c == 34 then
      return table.concat(parts), j + 1
    elseif c == 92 then
      j = j + 1
      local esc = s:sub(j, j)
      if esc == "n" then parts[#parts+1] = "\n"
      elseif esc == "t" then parts[#parts+1] = "\t"
      elseif esc == "r" then parts[#parts+1] = "\r"
      elseif esc == "\\" then parts[#parts+1] = "\\"
      elseif esc == '"' then parts[#parts+1] = '"'
      elseif esc == "/" then parts[#parts+1] = "/"
      elseif esc == "u" then
        -- Python's json.dumps escapes ALL non-ASCII as \uXXXX by default,
        -- so without this every accented filename/caption was garbled and
        -- the applicator's filename lookup silently missed.
        local hex = s:sub(j + 1, j + 4)
        if hex:match("^%x%x%x%x$") then
          local cp = tonumber(hex, 16)
          j = j + 4
          if cp >= 0xD800 and cp <= 0xDBFF and s:sub(j + 1, j + 2) == "\\u" then
            local hex2 = s:sub(j + 3, j + 6)
            local lo = hex2:match("^%x%x%x%x$") and tonumber(hex2, 16)
            if lo and lo >= 0xDC00 and lo <= 0xDFFF then
              cp = 0x10000 + (cp - 0xD800) * 0x400 + (lo - 0xDC00)
              j = j + 6
            end
          end
          parts[#parts+1] = utf8_encode(cp)
        else
          parts[#parts+1] = esc
        end
      else parts[#parts+1] = esc end
    else
      parts[#parts+1] = string.char(c)
    end
    j = j + 1
  end
  return nil, i
end

local function parse_number(s, i)
  local num_str = s:match("^-?%d+%.?%d*[eE]?[+-]?%d*()", i)
  if not num_str then return nil, i end
  local val = tonumber(s:sub(i, num_str - 1))
  return val, num_str
end

local parse_value

local function parse_object(s, i)
  if s:byte(i) ~= 123 then return nil, i end
  i = skip_ws(s, i + 1)
  local obj = {}
  if s:byte(i) == 125 then return obj, i + 1 end
  while true do
    i = skip_ws(s, i)
    local key, ni = parse_string(s, i)
    if key == nil then return nil, i end
    i = skip_ws(s, ni)
    if s:byte(i) ~= 58 then return nil, i end
    i = skip_ws(s, i + 1)
    local val
    val, i = parse_value(s, i)
    if val == nil then return nil, i end
    if val ~= M.null then obj[key] = val end
    i = skip_ws(s, i)
    local c = s:byte(i)
    if c == 125 then return obj, i + 1 end
    if c ~= 44 then return nil, i end
    i = i + 1
  end
end

local function parse_array(s, i)
  if s:byte(i) ~= 91 then return nil, i end
  i = skip_ws(s, i + 1)
  local arr = {}
  if s:byte(i) == 93 then return arr, i + 1 end
  while true do
    local val
    val, i = parse_value(s, i)
    if val == nil then return nil, i end
    arr[#arr+1] = val  -- M.null kept so element positions survive
    i = skip_ws(s, i)
    local c = s:byte(i)
    if c == 93 then return arr, i + 1 end
    if c ~= 44 then return nil, i end
    i = skip_ws(s, i + 1)
  end
end

parse_value = function(s, i)
  i = skip_ws(s, i)
  local c = s:byte(i)
  if c == 34 then return parse_string(s, i) end
  if c == 123 then return parse_object(s, i) end
  if c == 91 then return parse_array(s, i) end
  if c == 116 and s:sub(i, i+3) == "true" then return true, i + 4 end
  if c == 102 and s:sub(i, i+4) == "false" then return false, i + 5 end
  if c == 110 and s:sub(i, i+3) == "null" then return M.null, i + 4 end
  return parse_number(s, i)
end

function M.decode(s)
  local val, _ = parse_value(s, 1)
  return val
end

return M

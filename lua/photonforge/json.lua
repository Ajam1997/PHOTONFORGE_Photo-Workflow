local M = {}

local function skip_ws(s, i)
  return s:match("^%s*()", i)
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
    obj[key] = val
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
    arr[#arr+1] = val
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
  if c == 110 and s:sub(i, i+3) == "null" then return nil, i + 4 end
  return parse_number(s, i)
end

function M.decode(s)
  local val, _ = parse_value(s, 1)
  return val
end

return M

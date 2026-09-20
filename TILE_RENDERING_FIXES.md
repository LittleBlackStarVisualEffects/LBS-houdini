# Tile Rendering Fixes

## Issues Fixed

### 1. Only 1 Tile Rendering Per Frame
**Problem**: Each tile was rendering as a single frame instead of rendering all frames in the sequence.

**Fix in `extract_usd_render_tile.py`**:
- Modified `render_tile()` to properly detect frame tokens in USD filenames
- If USD file has `$F` tokens, render the full frame range with `-f start end`
- If single USD file, render once with the region

### 2. Missing Output Files Error
**Problem**: `extract_render.py` was being called for tile instances and looking for files with wrong naming.

**Fix in `extract_render.py`**:
- Added check to skip instances with `is_tile_render` flag
- Added check to skip instances with `tile_assembly` flag
- These are now handled by their own extractors

### 3. Tile Instances Inheriting Farm Flag
**Problem**: Tile instances inherited `farm=True` from parent, causing farm extraction logic to run instead of local rendering.

**Fix in `collect_usd_render_tiles.py`**:
- Set `tile_data["farm"] = False` for all tile instances
- Tile instances will process locally or be submitted separately to farm

### 4. USD File Not Found in Tile Extractor
**Problem**: Tile instances don't have `ifdFile` set, so renderer couldn't find USD to render.

**Fix in `extract_usd_render_tile.py`**:
- Added fallback logic to read USD file from ROP node parameters
- Uses `evalParmNoFrame()` to get `lopoutput` and `savetodirectory_directory`
- Constructs full path to USD file if not in instance data

## Files Modified

1. **`extract_render.py`**: Skip tile and assembly instances
2. **`extract_usd_render_tile.py`**: 
   - Better render target checking
   - Frame range rendering support
   - USD file fallback logic
   - Proper husk command construction
3. **`collect_usd_render_tiles.py`**: Mark tile instances with `farm=False`

## Testing Checklist

- [ ] Test with 2x2 tile grid - should create 4 tile instances
- [ ] Test local rendering - each tile should render full frame range
- [ ] Check log output for tile coordinates and frame ranges
- [ ] Verify output files are created with `_tile000`, `_tile001`, etc. suffixes
- [ ] Test frame sequences (not just single frame)
- [ ] Test with different tile counts (4x4, 3x2, etc.)
- [ ] Test assembly after tiles complete

## Debugging Commands

If you encounter issues, check:

```python
# In Python console to verify ROP has tile parameters:
import hou
rop = hou.node("/out/usdrender_node")
print("enable_tiling:", rop.evalParm("enable_tiling"))
print("tile_x:", rop.evalParm("tile_x"))
print("tile_y:", rop.evalParm("tile_y"))

# Check if USD file exists:
from ayon_houdini.api.lib import evalParmNoFrame
folder = evalParmNoFrame(rop, "savetodirectory_directory")
output = evalParmNoFrame(rop, "lopoutput")
import os
usd_path = os.path.join(folder, output)
print("USD Path:", usd_path)
print("Exists:", os.path.exists(usd_path))
```

## Expected Output

For a 2x2 tile render on frames 1001-1005:

```
beauty_tile000.1001.exr  (top-left)
beauty_tile001.1001.exr  (top-right)
beauty_tile002.1001.exr  (bottom-left)
beauty_tile003.1001.exr  (bottom-right)
... (repeated for each frame)

After assembly:
beauty.1001.exr (stitched from all tiles)
beauty.1002.exr (stitched from all tiles)
... etc
```

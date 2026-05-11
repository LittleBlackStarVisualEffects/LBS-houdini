# USD Render (Karma) Tile Rendering

## Overview

This feature adds tile-based rendering support to USD Render (Karma) in the AYON Houdini pipeline. Large resolution renders can be split into smaller rectangular tiles that are rendered separately and then assembled back into the final image.

## Benefits

- **Parallel Processing**: Multiple tiles can be rendered simultaneously on a farm
- **Memory Efficiency**: Each tile requires less memory than the full image
- **Fault Tolerance**: If one tile fails, only that tile needs to be re-rendered
- **Scalability**: More machines = faster completion for large renders

## Components

### 1. Creator Plugin (`create_usdrender.py`)

**No modifications needed**: Tile rendering is controlled via ROP node parameters, not creator parameters.

Users configure tiling directly on the USD Render ROP node in Houdini using spare parameters or custom HDA parameters.

### 2. Collector Plugin (`collect_usd_render_tiles.py`)

**New File**: Collects and creates tile instances

**Functionality**:
- Runs after the regular render products collector
- Reads tile settings directly from the ROP node parameters:
  - `enable_tiling`: Toggle tile rendering on/off
  - `tile_x`: Number of tiles in X direction
  - `tile_y`: Number of tiles in Y direction
- If tile rendering is enabled, creates separate instances for each tile
- Each tile instance contains:
  - Unique product name (e.g., `beauty_tile000`, `beauty_tile001`)
  - Tile coordinates (x_index, y_index)
  - Tile grid dimensions
  - Modified expected file paths with tile suffix
- Marks the original instance for assembly only

**ROP Parameter Names** (configurable in plugin):
- `tile_enable_parm = "enable_tiling"`
- `tile_x_parm = "tile_x"`
- `tile_y_parm = "tile_y"`

**Order**: `CollectorOrder + 0.05` (runs after `CollectRenderProducts`)

### 3. Extractor Plugin (`extract_usd_render_tile.py`)

**New File**: Renders individual tiles using Husk

**Functionality**:
- Processes only tile render instances (skips non-tile instances)
- Calculates normalized tile region coordinates (0.0 to 1.0)
- Invokes Husk (Karma standalone renderer) with region parameters:
  ```bash
  husk --renderer "Karma CPU" -R x1 x2 y1 y2 -f start end usd_file
  ```
- Verifies that rendered tile files exist

**Region Coordinates**:
- Origin: Top-left (0, 0)
- X-axis: Left (0.0) to Right (1.0)
- Y-axis: Top (0.0) to Bottom (1.0)
- Example for 2x2 grid:
  - Tile 0: X[0.0-0.5] Y[0.0-0.5] (top-left)
  - Tile 1: X[0.5-1.0] Y[0.0-0.5] (top-right)
  - Tile 2: X[0.0-0.5] Y[0.5-1.0] (bottom-left)
  - Tile 3: X[0.5-1.0] Y[0.5-1.0] (bottom-right)

**Order**: `ExtractorOrder` (standard extraction)

### 4. Assembly Plugin (`extract_usd_render_tile_assembly.py`)

**New File**: Stitches tiles back into final image

**Functionality**:
- Processes only the main tile assembly instance
- Uses OpenImageIO's `oiiotool --mosaic` to combine tiles
- Preserves all EXR layers, channels, and metadata
- Supports multiple AOVs and frame sequences
- Optionally cleans up intermediate tile files

**Command Example**:
```bash
oiiotool --mosaic 2x2 tile000.exr tile001.exr tile002.exr tile003.exr -o final.exr
```

**Order**: `ExtractorOrder + 0.1` (runs after tile rendering)

## Usage

### Setting Up ROP Node for Tile Rendering

#### Method 1: Helper Script (Recommended)

Use the provided helper script to automatically add tile parameters:

1. In Houdini, select your USD Render ROP node(s)
2. Open the Python Source Editor (Alt+Shift+P)
3. Load and run: `scripts/add_tile_parameters.py`
4. Parameters will be added automatically

#### Method 2: Manual Setup

Add spare parameters to your USD Render ROP node:

1. In Houdini, select your USD Render ROP node
2. Right-click on the parameter interface → **Edit Parameter Interface**
3. Click **Create New Parameter** and add:
   - **Enable Tiling** (Toggle, internal name: `enable_tiling`)
   - **Tile X** (Integer, internal name: `tile_x`, default: 2, range: 1-16)
   - **Tile Y** (Integer, internal name: `tile_y`, default: 2, range: 1-16)
4. Click **Accept**

#### Method 3: HDA Template

Create a custom USD Render HDA with these parameters built-in for reusability across shots.

### Creating a Tile Render Job

1. In Houdini, configure your USD Render ROP:
   - Check **Enable Tiling**
   - Set **Tile X** count (e.g., 2)
   - Set **Tile Y** count (e.g., 2)
2. Select your LOP network or render camera
3. Open AYON Publisher
4. Create new instance → "USD Render"
5. In the publisher UI, configure:
   - **Render Target**: Choose "Farm Rendering" or "Local machine rendering"
6. Publish

### Render Target Modes

- **Local machine rendering**: Renders and assembles tiles locally
- **Farm Rendering**: Submits tile jobs to farm, assembles on completion
- **Farm Export & Farm Rendering**: Exports USD locally, renders tiles on farm

### File Naming Convention

**Original**: `/path/to/beauty.1001.exr`

**Tile Files**:
- `/path/to/beauty_tile000.1001.exr`
- `/path/to/beauty_tile001.1001.exr`
- `/path/to/beauty_tile002.1001.exr`
- `/path/to/beauty_tile003.1001.exr`

**Final Assembled**: `/path/to/beauty.1001.exr`

## Technical Details

### Husk Region Rendering

Husk (Karma's standalone renderer) supports region rendering via the `-R` flag:

```bash
husk -R x1 x2 y1 y2 [options] usd_file
```

Where:
- `x1, y1`: Normalized top-left corner of region (0.0 to 1.0)
- `x2, y2`: Normalized bottom-right corner of region (0.0 to 1.0)

### OpenImageIO Mosaic

The assembly uses `oiiotool --mosaic`:

```bash
oiiotool --mosaic WIDTHxHEIGHT input1 input2 ... -o output
```

- Tiles must be provided in left-to-right, top-to-bottom order
- All tiles must have the same pixel format and channels
- Automatically handles EXR with multiple layers

### Dependencies

- **Husk**: Included with Houdini (used for rendering)
- **OpenImageIO**: Included with Houdini (used for assembly)

## Farm Integration

For farm rendering, the tile instances can be submitted as separate jobs with dependencies:

1. **Export Job**: Exports USD file(s)
2. **Tile Jobs**: Render each tile (parallel, depend on export)
3. **Assembly Job**: Stitch tiles (depends on all tile jobs)

The AYON Deadline submitter can handle this workflow automatically.

## Limitations

### Current Implementation

- Only supports USD Render (Karma)
- **Requires custom ROP parameters**: You must add `enable_tiling`, `tile_x`, and `tile_y` parameters to your ROP nodes (use the helper script)
- Assumes tiles can be rendered independently (no inter-tile dependencies)
- Assembly requires all tiles to complete before starting

### Not Supported (Yet)

- Adaptive tile sizes
- Overlapping tiles (for filtering/AA)
- Progressive refinement
- Other renderers (Mantra, Arnold, Redshift)

## Future Enhancements

1. **Smart tile sizing**: Automatically calculate optimal tile counts based on resolution
2. **Overlap**: Add pixel overlap between tiles for better filtering
3. **Multi-renderer**: Extend to Mantra, Arnold, Redshift
4. **Resume**: Support resuming failed tile renders
5. **Preview**: Generate low-res preview during tile rendering

## Troubleshooting

### Tiles render but assembly fails

**Problem**: Missing oiiotool or incompatible tile sizes

**Solution**: 
- Verify OpenImageIO is installed: `which oiiotool`
- Check tile file sizes match expected resolution
- Review assembly log for specific error

### Seams visible between tiles

**Problem**: Tiles don't align perfectly

**Solution**:
- Ensure tile counts divide resolution evenly
- Use pixel filtering that doesn't cross tile boundaries
- Consider adding tile overlap (future enhancement)

### Farm jobs fail with region errors

**Problem**: Husk version doesn't support `-R` flag

**Solution**:
- Verify Houdini version >= 18.5 (when `-R` was added)
- Check Husk documentation for your version

## Example: 4K Render in 16 Tiles

**Setup**:
- Resolution: 3840 x 2160
- Tiles: 4x4 = 16 tiles
- Each tile: 960 x 540 pixels

**Process**:
1. Exports `__render__.usd`
2. Renders 16 tiles in parallel:
   - `beauty_tile000.1001.exr` through `beauty_tile015.1001.exr`
3. Assembles into `beauty.1001.exr`

**Time Savings**: With 16 farm nodes, renders ~16x faster (minus assembly overhead)

## See Also

- Houdini Documentation: [USD Render ROP](https://www.sidefx.com/docs/houdini/nodes/out/usdrender.html)
- Karma Documentation: [Husk Command Line](https://www.sidefx.com/docs/houdini/rendering/husk.html)
- OpenImageIO: [oiiotool](https://openimageio.readthedocs.io/en/latest/oiiotool.html)

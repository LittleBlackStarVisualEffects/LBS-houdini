"""
Helper script to add tile rendering parameters to USD Render ROP nodes.

This script adds the necessary spare parameters for tile rendering to selected
USD Render ROP nodes or creates a template that can be applied to ROP nodes.

Usage:
    1. Select USD Render ROP node(s) in Houdini
    2. Run this script in the Python Source Editor
    3. Tile parameters will be added as spare parameters

Parameters added:
    - enable_tiling (Toggle): Enable/disable tile rendering
    - tile_x (Integer): Number of tiles in X direction
    - tile_y (Integer): Number of tiles in Y direction
"""

import hou


def add_tile_parameters_to_rop(rop_node):
    """Add tile rendering spare parameters to a USD Render ROP node.
    
    Args:
        rop_node (hou.Node): The USD Render ROP node to add parameters to
    
    Returns:
        bool: True if parameters were added successfully
    """
    if not rop_node:
        print("No node provided")
        return False
    
    # Check if node is a USD Render ROP
    if rop_node.type().name() != "usdrender":
        print(f"Warning: Node '{rop_node.path()}' is not a USD Render ROP (type: {rop_node.type().name()})")
        # Continue anyway - might work on other ROP types
    
    ptg = rop_node.parmTemplateGroup()
    
    # Create a folder for tile rendering parameters
    folder = hou.FolderParmTemplate("tile_rendering_folder", "Tile Rendering")
    
    # Enable tiling toggle
    enable_tiling = hou.ToggleParmTemplate(
        "enable_tiling",
        "Enable Tile Rendering",
        default_value=False,
        help="Split render into tiles for parallel processing"
    )
    folder.addParmTemplate(enable_tiling)
    
    # Tile X count
    tile_x = hou.IntParmTemplate(
        "tile_x",
        "Tiles X",
        1,
        default_value=(2,),
        min=1,
        max=16,
        min_is_strict=True,
        max_is_strict=False,
        help="Number of tiles in X direction (horizontal)"
    )
    tile_x.setConditional(hou.parmCondType.DisableWhen, "{ enable_tiling == 0 }")
    folder.addParmTemplate(tile_x)
    
    # Tile Y count
    tile_y = hou.IntParmTemplate(
        "tile_y",
        "Tiles Y",
        1,
        default_value=(2,),
        min=1,
        max=16,
        min_is_strict=True,
        max_is_strict=False,
        help="Number of tiles in Y direction (vertical)"
    )
    tile_y.setConditional(hou.parmCondType.DisableWhen, "{ enable_tiling == 0 }")
    folder.addParmTemplate(tile_y)
    
    # Add total tiles info (read-only expression)
    total_tiles = hou.IntParmTemplate(
        "total_tiles",
        "Total Tiles",
        1,
        default_value=(4,),
        help="Total number of tiles (read-only)"
    )
    total_tiles.setDefaultExpression(("ch('tile_x') * ch('tile_y')",))
    total_tiles.setConditional(hou.parmCondType.DisableWhen, "{ enable_tiling == 0 }")
    total_tiles.setLockType(hou.parmTemplateType.Int, (True,))  # Read-only
    folder.addParmTemplate(total_tiles)
    
    # Check if parameters already exist
    if ptg.find("enable_tiling"):
        print(f"Tile parameters already exist on '{rop_node.path()}'. Skipping.")
        return False
    
    # Add the folder to the parameter template group
    # Try to add after 'trange' parameter if it exists, otherwise at the end
    try:
        trange_parm = ptg.find("trange")
        if trange_parm:
            ptg.insertAfter(trange_parm, folder)
        else:
            ptg.append(folder)
    except:
        ptg.append(folder)
    
    rop_node.setParmTemplateGroup(ptg)
    
    print(f"✓ Added tile rendering parameters to '{rop_node.path()}'")
    return True


def main():
    """Main function - adds tile parameters to selected nodes."""
    selected_nodes = hou.selectedNodes()
    
    if not selected_nodes:
        hou.ui.displayMessage(
            "No nodes selected. Please select one or more USD Render ROP nodes.",
            severity=hou.severityType.Warning
        )
        return
    
    success_count = 0
    for node in selected_nodes:
        if add_tile_parameters_to_rop(node):
            success_count += 1
    
    if success_count > 0:
        hou.ui.displayMessage(
            f"Successfully added tile rendering parameters to {success_count} node(s).",
            severity=hou.severityType.Message
        )
    else:
        hou.ui.displayMessage(
            "No parameters were added. Check the console for details.",
            severity=hou.severityType.Warning
        )


# Run the script
if __name__ == "__main__":
    main()

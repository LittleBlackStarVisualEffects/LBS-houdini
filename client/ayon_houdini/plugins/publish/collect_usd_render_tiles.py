"""Collect USD Render Tiles for tile-based rendering."""
import hou
import pyblish.api

from ayon_houdini.api import plugin


class CollectUsdRenderTiles(plugin.HoudiniInstancePlugin):
    """Collect USD Render Tiles.

    If tile rendering is enabled on the USD Render ROP node, this plugin will
    create separate instances for each tile to be rendered. Each tile instance
    will have tile-specific data including tile index, tile coordinates, and
    modified output paths.

    This reads tile settings directly from the ROP node parameters:
    - Tile enable parameter (e.g., 'vm_tile', 'enable_tiling', etc.)
    - Tile X count (e.g., 'vm_tilex', 'tile_x')
    - Tile Y count (e.g., 'vm_tiley', 'tile_y')

    The parameter names can be customized via the plugin settings.

    This allows rendering large images by splitting them into smaller tiles
    that can be rendered in parallel on a farm, then assembled back together.

    The original instance is preserved as a 'main' instance that will handle
    the tile assembly after all tiles are rendered.

    """

    label = "Collect USD Render Tiles"
    order = pyblish.api.CollectorOrder + 0.05
    families = ["usdrender"]

    # ROP parameter names for tile settings (Husk tile rendering)
    tile_enable_parm = "husk_tile"
    tile_x_parm = "husk_tilecount1"
    tile_y_parm = "husk_tilecount2"
    tile_index_parm = "husk_tileindex"

    def process(self, instance):

        rop_node = hou.node(instance.data.get("instance_node"))
        if not rop_node:
            self.log.warning("No ROP node found for instance.")
            return

        # Check if tile rendering is enabled on the ROP node
        tile_rendering = False
        if rop_node.parm(self.tile_enable_parm):
            tile_rendering = bool(rop_node.evalParm(self.tile_enable_parm))
            self.log.info("Found tile enable parameter '%s' = %s", self.tile_enable_parm, tile_rendering)
        else:
            self.log.info(
                "Tile enable parameter '%s' not found on ROP node '%s'.",
                self.tile_enable_parm,
                rop_node.path()
            )
            self.log.info("Available parameters on ROP (first 20): %s", 
                         [p.name() for p in rop_node.parms()][:20])
            return

        if not tile_rendering:
            self.log.debug("Tile rendering is disabled on ROP node. Skipping.")
            return

        # Read tile counts from ROP node
        tile_x = 2  # default
        tile_y = 2  # default

        if rop_node.parm(self.tile_x_parm):
            tile_x = int(rop_node.evalParm(self.tile_x_parm))
        else:
            self.log.warning(
                "Tile X parameter '%s' not found on ROP node. Using default: %s",
                self.tile_x_parm, tile_x
            )

        if rop_node.parm(self.tile_y_parm):
            tile_y = int(rop_node.evalParm(self.tile_y_parm))
        else:
            self.log.warning(
                "Tile Y parameter '%s' not found on ROP node. Using default: %s",
                self.tile_y_parm, tile_y
            )

        if tile_x < 1 or tile_y < 1:
            self.log.warning(
                "Invalid tile counts (X: %s, Y: %s). Tile rendering disabled.",
                tile_x, tile_y
            )
            return

        total_tiles = tile_x * tile_y
        self.log.info(
            "Tile rendering enabled on ROP: %sx%s = %s tiles",
            tile_x, tile_y, total_tiles
        )

        # Mark the original instance as a tile assembly job
        instance.data["tile_assembly"] = True
        instance.data["tile_x"] = tile_x
        instance.data["tile_y"] = tile_y
        instance.data["total_tiles"] = total_tiles

        # Store original expected files for assembly
        original_expected_files = instance.data.get("expectedFiles", [])
        # Use shallow copy instead of deepcopy to avoid pickling issues
        if isinstance(original_expected_files, list):
            instance.data["tile_original_expected_files"] = original_expected_files.copy()
        else:
            instance.data["tile_original_expected_files"] = original_expected_files

        # Create individual tile instances
        context = instance.context
        for tile_idx in range(total_tiles):
            # Calculate tile coordinates (0-based)
            tile_x_idx = tile_idx % tile_x
            tile_y_idx = tile_idx // tile_x

            self.log.info(f"Creating tile instance {tile_idx} of {total_tiles}")

            tile_instance = self.create_tile_instance(
                instance=instance,
                context=context,
                tile_idx=tile_idx,
                tile_x_idx=tile_x_idx,
                tile_y_idx=tile_y_idx,
                tile_x=tile_x,
                tile_y=tile_y
            )

            context.append(tile_instance)
            self.log.info(
                "Created tile instance: %s (tile %s/%s at X:%s Y:%s)",
                tile_instance.data["productName"],
                tile_idx + 1,
                total_tiles,
                tile_x_idx,
                tile_y_idx
            )

        # The original instance should not render directly
        # It will only handle tile assembly
        instance.data["render_tiles_only"] = True

    def create_tile_instance(
        self,
        instance,
        context,
        tile_idx,
        tile_x_idx,
        tile_y_idx,
        tile_x,
        tile_y
    ):
        """Create a tile-specific render instance.

        Args:
            instance: Original instance
            context: Pyblish context
            tile_idx: Tile index (0-based, increments left-to-right,
                top-to-bottom)
            tile_x_idx: Tile X coordinate (0-based)
            tile_y_idx: Tile Y coordinate (0-based)
            tile_x: Total number of tiles in X
            tile_y: Total number of tiles in Y

        Returns:
            pyblish.api.Instance: Tile render instance

        """
        # Create a shallow copy of instance data, avoiding deepcopy which fails
        # on Houdini objects (WeakMethod) - we'll selectively copy what we need
        tile_data = {}
        
        # Copy serializable data from the original instance
        for key, value in instance.data.items():
            try:
                # Skip objects that can't be copied (Houdini nodes, etc.)
                if key in ["instance_node", "node", "rop_node"]:
                    # Keep the reference as-is
                    tile_data[key] = value
                elif isinstance(value, (dict, list)):
                    # Try to shallow copy collections
                    if isinstance(value, dict):
                        tile_data[key] = value.copy()
                    else:
                        tile_data[key] = value.copy() if hasattr(value, 'copy') else list(value)
                elif isinstance(value, (str, int, float, bool, type(None))):
                    # Primitive types - copy directly
                    tile_data[key] = value
                else:
                    # For other types, just reference them
                    tile_data[key] = value
            except Exception as e:
                self.log.debug("Could not copy key '%s': %s - using reference", key, e)
                tile_data[key] = value

        # Modify product name to include tile index
        original_product_name = tile_data["productName"]
        tile_product_name = f"{original_product_name}_tile{tile_idx:03d}"
        tile_data["productName"] = tile_product_name
        tile_data["name"] = tile_product_name

        # Add tile-specific data
        tile_data["tile_index"] = tile_idx
        tile_data["tile_x_index"] = tile_x_idx
        tile_data["tile_y_index"] = tile_y_idx
        tile_data["tile_x_count"] = tile_x
        tile_data["tile_y_count"] = tile_y
        tile_data["tile_parent_instance"] = instance.data["productName"]
        tile_data["is_tile_render"] = True
        
        # Mark to skip validations - tiles share the same ROP intentionally
        tile_data["skip_render_product_paths_unique_check"] = True
        tile_data["validate_unique_subsets"] = False
        
        # Ensure tile instances skip farm collection (they run locally or as separate farm jobs)
        # Farm instances will be created as needed by deadline plugin
        tile_data["farm"] = False

        # Modify expected files to include tile suffix
        if "expectedFiles" in tile_data:
            tile_data["expectedFiles"] = self.modify_expected_files_for_tile(
                tile_data["expectedFiles"],
                tile_idx
            )

        # Create the tile instance
        tile_instance = context.create_instance(tile_product_name)
        tile_instance.data.update(tile_data)

        # Copy any additional instance members
        tile_instance[:] = instance[:]

        return tile_instance

    def modify_expected_files_for_tile(self, expected_files, tile_idx):
        """Modify expected files to include tile suffix in filenames.

        Args:
            expected_files: Original expected files structure
            tile_idx: Tile index

        Returns:
            Modified expected files with tile suffix

        """
        if not expected_files:
            return expected_files

        modified_files = []
        for file_entry in expected_files:
            if isinstance(file_entry, dict):
                # Modify each AOV entry
                modified_entry = {}
                for aov_name, files in file_entry.items():
                    if isinstance(files, str):
                        # Single file
                        modified_entry[aov_name] = self.add_tile_suffix(
                            files, tile_idx
                        )
                    elif isinstance(files, list):
                        # File sequence
                        modified_entry[aov_name] = [
                            self.add_tile_suffix(f, tile_idx) for f in files
                        ]
                    else:
                        modified_entry[aov_name] = files
                modified_files.append(modified_entry)
            else:
                modified_files.append(file_entry)

        return modified_files

    def add_tile_suffix(self, filepath, tile_idx):
        """Add tile suffix to a filepath before the extension.

        Examples:
            /path/beauty.1001.exr -> /path/beauty_tile000.1001.exr
            /path/beauty.####.exr -> /path/beauty_tile000.####.exr

        Args:
            filepath: Original file path
            tile_idx: Tile index

        Returns:
            str: Modified file path with tile suffix

        """
        import os

        if not filepath:
            return filepath

        dirname = os.path.dirname(filepath)
        basename = os.path.basename(filepath)

        # Find the first dot that separates name from extension/frame
        parts = basename.split(".")
        if len(parts) > 1:
            # Insert tile suffix before the first dot
            name = parts[0]
            rest = ".".join(parts[1:])
            new_basename = f"{name}_tile{tile_idx:03d}.{rest}"
        else:
            # No extension, append tile suffix
            new_basename = f"{basename}_tile{tile_idx:03d}"

        return os.path.join(dirname, new_basename).replace("\\", "/")

"""Extract USD Render Tiles using Husk with tile parameters."""
import os
import hou
import pyblish.api

from ayon_core.pipeline import PublishError
from ayon_houdini.api import plugin


class ExtractUsdRenderTile(plugin.HoudiniExtractorPlugin):
    """Extract individual render tiles for USD Render.

    This plugin renders individual tiles by invoking Husk (the Karma
    standalone renderer) with tile-specific parameters. It uses the
    -R (region) flag to specify which portion of the image to render.

    The region is specified as normalized coordinates (0.0 to 1.0):
        -R x1 x2 y1 y2

    Where:
        - x1, y1 = top-left corner of the tile
        - x2, y2 = bottom-right corner of the tile
        - Origin is top-left
        - Y-axis points down

    """

    order = pyblish.api.ExtractorOrder
    label = "Extract USD Render Tile"
    families = ["usdrender"]

    def process(self, instance):

        # Only process tile render instances
        if not instance.data.get("is_tile_render", False):
            self.log.debug(
                "Instance '%s' is not a tile render (is_tile_render=%s). Skipping.",
                instance.data.get("productName"),
                instance.data.get("is_tile_render")
            )
            return

        try:
            self.log.info(
                "Processing tile render instance: %s (tile_index=%s)",
                instance.data.get("productName"),
                instance.data.get("tile_index")
            )

            # Check render target from instance data
            render_target = None
            creator_attributes = instance.data.get("creator_attributes", {})
            if creator_attributes:
                render_target = creator_attributes.get("render_target")

            self.log.debug(
                "Tile %s - render_target=%s, farm=%s",
                instance.data.get("tile_index"),
                render_target,
                instance.data.get("farm")
            )

            # Skip if this is a farm render (farm will handle the rendering)
            # But local rendering should always proceed
            if instance.data.get("farm"):
                if render_target not in {"local", "local_export_farm_render"}:
                    self.log.debug(
                        "Tile render job marked for farm (not local). "
                        "Farm will handle rendering separately."
                    )
                    return
                else:
                    self.log.debug(
                        "Local rendering enabled for farm split mode. Proceeding with tile render."
                    )

            self.log.info("Rendering tile %s", instance.data["tile_index"])

            # Get tile coordinates
            tile_x_idx = instance.data["tile_x_index"]
            tile_y_idx = instance.data["tile_y_index"]
            tile_x_count = instance.data["tile_x_count"]
            tile_y_count = instance.data["tile_y_count"]

            # Calculate normalized tile region (0.0 to 1.0)
            # Husk uses normalized coordinates where (0,0) is top-left
            x1 = tile_x_idx / tile_x_count
            x2 = (tile_x_idx + 1) / tile_x_count
            y1 = tile_y_idx / tile_y_count
            y2 = (tile_y_idx + 1) / tile_y_count

            # Get the USD file to render
            # First try the tile-specific ifdFile, then fall back to original
            usd_file = instance.data.get("ifdFile")
            self.log.debug("Initial ifdFile from instance: %s", usd_file)
            
            if not usd_file:
                # Try to get from the ROP node's lopoutput parameter
                rop_node = hou.node(instance.data.get("instance_node"))
                if rop_node:
                    from ayon_houdini.api.lib import evalParmNoFrame
                    usd_output = evalParmNoFrame(rop_node, "lopoutput")
                    
                    # Get the directory where USD is saved
                    try:
                        folder = evalParmNoFrame(rop_node, "savetodirectory_directory")
                        usd_file = os.path.join(folder, usd_output).replace("\\", "/")
                        self.log.debug(
                            "USD file from ROP node: folder=%s, output=%s -> %s",
                            folder, usd_output, usd_file
                        )
                    except Exception as e:
                        self.log.warning("Failed to get USD path from ROP: %s", e)
                        pass
            
            if not usd_file:
                raise PublishError(
                    "No USD file found to render for tile. "
                    "Make sure the USD export completed successfully."
                )

            # Expand any frame tokens in the USD file path
            if "$F" in usd_file:
                frame = instance.data.get("frameStartHandle")
                if frame is not None:
                    # Replace $F4 with padded frame number
                    import re
                    def replace_frame(match):
                        padding = match.group(2)
                        if padding:
                            return str(int(frame)).zfill(int(padding))
                        return str(int(frame))
                    
                    expanded_usd_file = re.sub(r"\$F(\d*)", replace_frame, usd_file)
                    self.log.debug(
                        "Expanded USD file path: %s -> %s",
                        usd_file, expanded_usd_file
                    )
                    usd_file = expanded_usd_file

            if not os.path.exists(usd_file):
                raise PublishError(
                    f"USD file does not exist: {usd_file}\n"
                    "Make sure the USD export stage completed before rendering tiles."
                )
            
            self.log.info("Using USD file for tile render: %s", usd_file)

            self.log.info(
                "Rendering tile %s - Region X[%.3f-%.3f] Y[%.3f-%.3f]",
                instance.data["tile_index"],
                x1, x2, y1, y2
            )

            # Render the tile using husk with region parameters
            self.render_tile(
                instance=instance,
                usd_file=usd_file,
                region=(x1, x2, y1, y2)
            )

            # Verify rendered files exist
            self.verify_tile_output(instance)
            
            self.log.info("Tile %s rendering completed successfully", instance.data["tile_index"])
        
        except Exception as e:
            self.log.error(
                "ERROR processing tile %s: %s",
                instance.data.get("tile_index", "UNKNOWN"),
                str(e),
                exc_info=True
            )
            raise

    def render_tile(self, instance, usd_file, region):
        """Render a tile using Husk by setting tile index.

        Args:
            instance: Pyblish instance
            usd_file: Path to USD file to render
            region: Tuple of (x1, x2, y1, y2) - not used, kept for compatibility

        """
        import subprocess

        rop_node = hou.node(instance.data["instance_node"])

        # Get renderer
        renderer = rop_node.evalParm("renderer")
        
        # Get frame range
        frame_start = int(instance.data.get("frameStartHandle", 1))
        frame_end = int(instance.data.get("frameEndHandle", 1))
        
        # Get tile index
        tile_index = instance.data["tile_index"]
        tile_x_count = instance.data["tile_x_count"]
        tile_y_count = instance.data["tile_y_count"]

        # Build husk command
        husk_exe = os.path.join(hou.homeDir(), "bin", "husk")

        # If USD file has frame tokens, we need to render per-frame
        has_frame_token = "$F" in usd_file or "#" in usd_file
        
        self.log.debug(
            "Husk render setup: tile_index=%s, tile_count=%sx%s, has_frame_token=%s",
            tile_index, tile_x_count, tile_y_count, has_frame_token
        )

        # Set tile parameters on ROP before rendering
        self.log.debug(
            "Setting ROP tile parameters: husk_tilecount1=%s, husk_tilecount2=%s, husk_tileindex=%s",
            tile_x_count, tile_y_count, tile_index
        )
        rop_node.setParms({
            "husk_tilecount1": tile_x_count,
            "husk_tilecount2": tile_y_count,
            "husk_tileindex": tile_index
        })

        if has_frame_token:
            # Render frame range with tile index
            cmd = [
                husk_exe,
                "--renderer", renderer,
                "-f", str(frame_start), str(frame_end),  # Frame range
                "-V", "2"  # Verbosity
            ]
            # USD file with frame tokens
            cmd.append(usd_file)
            self.log.info(
                "Tile %s: Rendering frame range %s-%s with tile index %s (grid %sx%s)",
                instance.data["tile_index"],
                frame_start, frame_end,
                tile_index,
                tile_x_count, tile_y_count
            )
        else:
            # Single USD file - render once
            cmd = [
                husk_exe,
                "--renderer", renderer,
                "-V", "2"  # Verbosity
            ]
            cmd.append(usd_file)
            self.log.info(
                "Tile %s: Rendering single USD file with tile index %s (grid %sx%s)",
                instance.data["tile_index"],
                tile_index,
                tile_x_count, tile_y_count
            )

        self.log.debug("Husk command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True,
                cwd=hou.homeDir()
            )
            
            if result.stdout:
                self.log.debug("Husk output:\n%s", result.stdout)
            if result.stderr:
                self.log.debug("Husk stderr:\n%s", result.stderr)

        except subprocess.CalledProcessError as e:
            error_msg = f"Husk rendering failed with exit code {e.returncode}"
            if e.stdout:
                error_msg += f"\nStdout:\n{e.stdout}"
            if e.stderr:
                error_msg += f"\nStderr:\n{e.stderr}"
            raise PublishError(error_msg)

        except Exception as e:
            raise PublishError(f"Failed to execute husk: {e}")

    def verify_tile_output(self, instance):
        """Verify that the tile rendered successfully and output files exist.

        Args:
            instance: Pyblish instance

        Raises:
            PublishError: If expected output files are missing

        """
        expected_files = instance.data.get("expectedFiles", [])
        tile_idx = instance.data.get("tile_index")
        
        self.log.debug(
            "Tile %s: Verifying output files. Expected files structure: %s",
            tile_idx, expected_files
        )
        
        if not expected_files:
            self.log.warning(
                "Tile %s: No expected files defined for verification.",
                tile_idx
            )
            return

        missing_files = []
        found_files = []
        
        for file_entry in expected_files:
            if isinstance(file_entry, dict):
                for aov_name, files in file_entry.items():
                    if isinstance(files, str):
                        if os.path.exists(files):
                            found_files.append(files)
                        else:
                            missing_files.append(files)
                    elif isinstance(files, list):
                        for f in files:
                            if os.path.exists(f):
                                found_files.append(f)
                            else:
                                missing_files.append(f)

        self.log.debug(
            "Tile %s: Found %d files, missing %d files",
            tile_idx, len(found_files), len(missing_files)
        )
        
        if found_files:
            self.log.info(
                "Tile %s: Found rendered files:\n%s",
                tile_idx,
                "\n".join(f"  - {f}" for f in found_files[:5])
            )

        if missing_files:
            missing_files_str = "\n".join(f"  - {f}" for f in missing_files)
            raise PublishError(
                f"Tile {tile_idx} rendering incomplete. Missing files:\n{missing_files_str}"
            )

        self.log.info(
            "Tile %s: All expected files verified (%d files)",
            tile_idx, len(found_files)
        )

"""Assemble rendered tiles into final image using OpenImageIO."""
import os
import pyblish.api

from ayon_core.pipeline import PublishError
from ayon_houdini.api import plugin


class ExtractUsdRenderTileAssembly(plugin.HoudiniExtractorPlugin):
    """Assemble rendered tiles into final image.

    This plugin runs after all individual tiles have been rendered and
    stitches them back together into the final full-resolution image.

    It uses OpenImageIO's oiiotool to combine the tiles, which supports:
    - EXR with all layers and channels
    - Proper color space handling
    - Deep images
    - Multiple AOVs

    The assembly process:
    1. Wait for all tile renders to complete
    2. For each AOV/frame combination:
       - Create a mosaic layout based on tile grid
       - Use oiiotool to combine tiles
       - Write out final assembled image
    3. Clean up intermediate tile files (optional)

    """

    order = pyblish.api.ExtractorOrder + 0.1
    label = "Assemble USD Render Tiles"
    families = ["usdrender"]

    # Whether to keep individual tile files after assembly
    keep_tile_files = False

    def process(self, instance):

        # Only process the main tile assembly instance
        if not instance.data.get("tile_assembly", False):
            return

        if instance.data.get("render_tiles_only", False):
            self.log.debug(
                "Instance is marked as tiles-only render. "
                "Skipping assembly (tiles will be assembled on farm)."
            )
            return

        # Check render target
        render_target = None
        creator_attributes = instance.data.get("creator_attributes", {})
        if creator_attributes:
            render_target = creator_attributes.get("render_target")

        # Only assemble if local rendering was done
        do_local_assembly = render_target in {"local"} if render_target else False

        if not do_local_assembly:
            self.log.debug(
                "Assembly not needed for render target: %s", render_target
            )
            return

        tile_x = instance.data["tile_x"]
        tile_y = instance.data["tile_y"]
        total_tiles = instance.data["total_tiles"]

        self.log.info(
            "Assembling %s tiles (%sx%s grid) into final images",
            total_tiles, tile_x, tile_y
        )

        # Get original expected files (before tile splitting)
        original_expected = instance.data.get(
            "tile_original_expected_files", []
        )

        if not original_expected:
            self.log.warning("No original expected files found for assembly.")
            return

        # Assemble each AOV/frame combination
        for file_entry in original_expected:
            if isinstance(file_entry, dict):
                for aov_name, files in file_entry.items():
                    if isinstance(files, str):
                        # Single file
                        self.assemble_file(
                            files, aov_name, tile_x, tile_y, total_tiles
                        )
                    elif isinstance(files, list):
                        # File sequence
                        for file_path in files:
                            self.assemble_file(
                                file_path, aov_name, tile_x, tile_y, total_tiles
                            )

        self.log.info("Tile assembly completed successfully.")

    def assemble_file(self, output_file, aov_name, tile_x, tile_y, total_tiles):
        """Assemble tiles for a single output file.

        Args:
            output_file: Target output file path
            aov_name: AOV/render pass name
            tile_x: Number of tiles in X
            tile_y: Number of tiles in Y
            total_tiles: Total number of tiles

        """
        import subprocess

        # Collect all tile files for this output
        tile_files = self.collect_tile_files(output_file, total_tiles)

        # Check that all tile files exist
        missing_tiles = [f for f in tile_files if not os.path.exists(f)]
        if missing_tiles:
            raise PublishError(
                f"Cannot assemble {output_file}: missing tile files:\n"
                + "\n".join(f"  - {f}" for f in missing_tiles)
            )

        self.log.info(
            "Assembling %s from %s tiles", 
            os.path.basename(output_file),
            len(tile_files)
        )

        # Use oiiotool to mosaic the tiles
        oiiotool = self.get_oiiotool_path()
        
        if not oiiotool or not os.path.exists(oiiotool):
            raise PublishError(
                "oiiotool not found. Cannot assemble tiles. "
                "Please ensure OpenImageIO is installed."
            )

        # Build mosaic command
        # oiiotool uses: --mosaic WIDTHxHEIGHT input1 input2 ... -o output
        cmd = [oiiotool]
        
        # Add mosaic operation
        cmd.extend(["--mosaic", f"{tile_x}x{tile_y}"])
        
        # Add all tile files in order (left-to-right, top-to-bottom)
        cmd.extend(tile_files)
        
        # Output file
        cmd.extend(["-o", output_file])

        self.log.debug("Executing oiiotool: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=True
            )
            
            if result.stdout:
                self.log.debug("oiiotool stdout: %s", result.stdout)
            if result.stderr:
                self.log.debug("oiiotool stderr: %s", result.stderr)

        except subprocess.CalledProcessError as e:
            error_msg = (
                f"Tile assembly failed with exit code {e.returncode}\n"
                f"Command: {' '.join(cmd)}"
            )
            if e.stdout:
                error_msg += f"\nStdout:\n{e.stdout}"
            if e.stderr:
                error_msg += f"\nStderr:\n{e.stderr}"
            raise PublishError(error_msg)

        except Exception as e:
            raise PublishError(f"Failed to execute oiiotool: {e}")

        # Verify assembled file exists
        if not os.path.exists(output_file):
            raise PublishError(
                f"Assembly appeared to succeed but output file not found: "
                f"{output_file}"
            )

        # Optionally clean up tile files
        if not self.keep_tile_files:
            self.cleanup_tile_files(tile_files)

    def collect_tile_files(self, output_file, total_tiles):
        """Get list of tile file paths for a given output file.

        Args:
            output_file: Original output file path
            total_tiles: Total number of tiles

        Returns:
            list: List of tile file paths in correct order

        """
        tile_files = []
        
        dirname = os.path.dirname(output_file)
        basename = os.path.basename(output_file)

        # Extract base name and extension
        parts = basename.split(".")
        if len(parts) > 1:
            name = parts[0]
            rest = ".".join(parts[1:])
        else:
            name = basename
            rest = ""

        for tile_idx in range(total_tiles):
            if rest:
                tile_basename = f"{name}_tile{tile_idx:03d}.{rest}"
            else:
                tile_basename = f"{name}_tile{tile_idx:03d}"
            
            tile_file = os.path.join(dirname, tile_basename)
            tile_files.append(tile_file)

        return tile_files

    def get_oiiotool_path(self):
        """Get path to oiiotool executable.

        Returns:
            str: Path to oiiotool or None if not found

        """
        import shutil
        import hou

        # Try to find oiiotool in Houdini installation
        houdini_bin = os.path.join(hou.homeDir(), "bin")
        oiiotool_houdini = os.path.join(houdini_bin, "oiiotool")
        
        if os.path.exists(oiiotool_houdini):
            return oiiotool_houdini

        # Try system PATH
        oiiotool_system = shutil.which("oiiotool")
        if oiiotool_system:
            return oiiotool_system

        # Not found
        self.log.warning(
            "oiiotool not found in Houdini bin (%s) or system PATH",
            houdini_bin
        )
        return None

    def cleanup_tile_files(self, tile_files):
        """Remove intermediate tile files after assembly.

        Args:
            tile_files: List of tile file paths to remove

        """
        for tile_file in tile_files:
            try:
                if os.path.exists(tile_file):
                    os.remove(tile_file)
                    self.log.debug("Removed tile file: %s", tile_file)
            except Exception as e:
                self.log.warning(
                    "Failed to remove tile file %s: %s", tile_file, e
                )

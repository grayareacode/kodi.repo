"""
Kodi repository builder.
Distilled from github.com/jurialmunkey/repository.jurialmunkey/_repo_generator.py
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

# Constants
KODI_VERSIONS = ["omega", "piers", "repo"]
IGNORE_PATTERNS = [
    ".git",
    ".github",
    ".gitignore",
    ".DS_Store",
    "thumbs.db",
    ".idea",
    "venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
]


def sizeof_fmt(num):
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


class Generator:
    def __init__(self, release_dir, force=False):
        self.release_path = Path(release_dir)
        self.force = force
        self.zips_path = self.release_path / "zips"
        self.zips_path.mkdir(parents=True, exist_ok=True)

        self._clean_binaries()
        if self._generate_addons_xml():
            self._generate_md5()

    def _clean_binaries(self):
        """Removes compiled python files and caches."""
        for p in self.release_path.rglob("*"):
            if p.name == "__pycache__" and p.is_dir():
                shutil.rmtree(p)
                print(f"Removed cache: {p}")
            elif p.suffix in {".pyc", ".pyo"} and p.is_file():
                p.unlink()
                print(f"Removed binary: {p}")

    def _should_ignore(self, path):
        """Check if path matches ignore patterns."""
        return any(
            pattern in path.parts or path.match(pattern) for pattern in IGNORE_PATTERNS
        )

    def _create_zip(self, addon_path, addon_id, version):
        zip_dir = self.zips_path / addon_id
        zip_dir.mkdir(exist_ok=True)
        zip_file = zip_dir / f"{addon_id}-{version}.zip"

        if zip_file.exists() and not self.force:
            print(f"Skipping existing: {addon_id} {version}")
            return

        with zipfile.ZipFile(zip_file, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in addon_path.rglob("*"):
                if file_path.is_file() and not self._should_ignore(file_path):
                    archive_name = file_path.relative_to(addon_path.parent)
                    zf.write(file_path, archive_name)

        print(
            f"Created zip: {addon_id} {version} - {sizeof_fmt(zip_file.stat().st_size)}"
        )

    def _copy_assets(self, addon_path, addon_xml_root):
        """Copy assets defined in addon.xml to the zips directory."""
        addon_id = addon_xml_root.get("id")
        assets = []

        # Standard assets
        assets.append("addon.xml")

        # Parse assets from extension points
        for ext in addon_xml_root.findall("extension"):
            if ext.get("point") in ["xbmc.addon.metadata", "kodi.addon.metadata"]:
                assets_node = ext.find("assets")
                if assets_node is not None:
                    assets.extend(asset.text for asset in assets_node if asset.text)

        dest_dir = self.zips_path / addon_id
        for asset in assets:
            src = addon_path / asset
            if src.exists():
                dest = dest_dir / asset
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, dest)

    def _generate_addons_xml(self):
        addons_xml_path = self.zips_path / "addons.xml"

        # Load existing or create new
        if addons_xml_path.exists():
            tree = ET.parse(addons_xml_path)
            root = tree.getroot()
        else:
            root = ET.Element("addons")
            tree = ET.ElementTree(root)

        changed = False
        found_ids = set()

        # Process all addons in release folder
        for addon_dir in [
            d
            for d in self.release_path.iterdir()
            if d.is_dir() and d.name != "zips" and not d.name.startswith(".")
        ]:
            xml_file = addon_dir / "addon.xml"
            if not xml_file.exists():
                continue

            try:
                addon_xml = ET.parse(xml_file)
                addon_root = addon_xml.getroot()
                addon_id = addon_root.get("id")
                version = addon_root.get("version")
                found_ids.add(addon_id)

                # Find existing entry
                existing = root.find(f"./addon[@id='{addon_id}']")

                if (
                    existing is not None
                    and existing.get("version") == version
                    and not self.force
                ):
                    continue

                # Update or Add
                if existing is not None:
                    root.remove(existing)

                root.append(addon_root)
                self._create_zip(addon_dir, addon_id, version)
                self._copy_assets(addon_dir, addon_root)
                changed = True

            except Exception as e:
                print(f"Error processing {addon_dir.name}: {e}")

        if changed:
            # Sort addons by ID
            root[:] = sorted(root, key=lambda child: child.get("id") or "")
            tree.write(addons_xml_path, encoding="utf-8", xml_declaration=True)
            print(f"Updated {addons_xml_path}")
            return True
        else:
            print(f"No changes for {self.release_path}")
            return False

    def _generate_md5(self):
        xml_path = self.zips_path / "addons.xml"
        md5_path = self.zips_path / "addons.xml.md5"

        md5_hash = hashlib.md5(xml_path.read_bytes()).hexdigest()
        md5_path.write_text(md5_hash, encoding="utf-8")
        print(f"Updated {md5_path}")


def update_submodules():
    """Update all git submodules."""
    try:
        print("Updating git submodules...")
        subprocess.check_call(
            ["git", "submodule", "update", "--init", "--recursive", "--remote"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print("Git submodules updated.")
    except subprocess.CalledProcessError as e:
        print(f"Failed to update git submodules: {e}")
    except FileNotFoundError:
        print("git command not found. Skipping submodule update.")


def create_repo_zip():
    """Create the repository zip file."""
    root_path = Path(".")
    xml_file = root_path / "addon.xml"

    if not xml_file.exists():
        print("Repo addon.xml not found. Skipping repo zip creation.")
        return

    try:
        tree = ET.parse(xml_file)
        root = tree.getroot()
        addon_id = root.get("id")
        version = root.get("version")

        zip_name = f"{addon_id}-{version}.zip"
        zip_path = root_path / zip_name

        print(f"Creating repo zip: {zip_name}")

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            files_to_zip = ["addon.xml", "icon.jpg", "fanart.jpg"]
            for file_name in files_to_zip:
                file_path = root_path / file_name
                if file_path.exists():
                    zf.write(file_path, f"{addon_id}/{file_name}")
                else:
                    print(f"Warning: {file_name} not found, skipping.")

        print(f"Created repo zip: {zip_name} - {sizeof_fmt(zip_path.stat().st_size)}")

        # Update index.html
        index_path = root_path / "index.html"
        html_content = f'<!DOCTYPE html>\n<a href="{zip_name}">{zip_name}</a>\n'
        index_path.write_text(html_content, encoding="utf-8")
        print(f"Updated index.html -> {zip_name}")

    except Exception as e:
        print(f"Error creating repo zip: {e}")


def main():
    parser = argparse.ArgumentParser(description="Build Kodi repository zips.")
    parser.add_argument(
        "releases", nargs="*", default=KODI_VERSIONS, help="Release directories"
    )
    parser.add_argument("--force", action="store_true", help="Force rebuild")
    args = parser.parse_args()

    # Update submodules before checking for directories
    update_submodules()

    # Create the repository zip
    create_repo_zip()

    # Filter valid directories
    dirs = [d for d in args.releases if os.path.isdir(d)]

    if not dirs:
        print("No valid release directories found.")
        return

    for release in dirs:
        Generator(release, force=args.force)


if __name__ == "__main__":
    main()

"""Fetch the three example PhysiCell simulation outputs into ``tests/data/example_physicell/``.

The Zenodo deposition publishes a single zip archive
(``example_physicell_simulations.zip``) containing ``sim_000``, ``sim_003``, and
``sim_014``. This script:

1. Downloads the archive (default) or accepts a local source.
2. Verifies the MD5 hash against :data:`ZENODO_MD5`.
3. Extracts the three ``sim_xxx`` directories into ``tests/data/example_physicell/``.
4. Optionally deletes the zip after extraction (``--keep-zip`` to retain).

Modes:

* **Zenodo (default):** ``uv run python scripts/fetch_example_data.py``
* **Local zip:** ``uv run python scripts/fetch_example_data.py --zip-path <path>``
* **Local directory:** ``uv run python scripts/fetch_example_data.py --from-local <dir-containing-sim_xxx>``
  (interim path used before the Zenodo upload existed; still useful for offline work.)

The destination is gitignored, so it is safe to populate with multi-GB outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ZENODO_RECORD_ID = "20148946"
ZENODO_FILENAME = "example_physicell_simulations.zip"
ZENODO_URL = f"https://zenodo.org/records/{ZENODO_RECORD_ID}/files/{ZENODO_FILENAME}?download=1"
ZENODO_MD5 = "9001e2a652799f6aa1485ead822ce5b7"
ZENODO_DOI = "10.5281/zenodo.20148946"

REPO_ROOT = Path(__file__).resolve().parent.parent
DEST_DIR = REPO_ROOT / "tests" / "data" / "example_physicell"
SIM_NAMES = ("sim_000", "sim_003", "sim_014")
CHUNK_BYTES = 1 << 20  # 1 MiB


def _ensure_dest() -> None:
    DEST_DIR.mkdir(parents=True, exist_ok=True)


def _all_sims_present() -> bool:
    return all((DEST_DIR / name).is_dir() for name in SIM_NAMES)


def _md5_of(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    print(f"[fetch] downloading {url}", file=sys.stderr)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, tmp.open("wb") as out:
        total = resp.headers.get("Content-Length")
        total_bytes = int(total) if total else None
        bytes_read = 0
        next_report = 64 * (1 << 20)  # report every 64 MiB
        while True:
            chunk = resp.read(CHUNK_BYTES)
            if not chunk:
                break
            out.write(chunk)
            bytes_read += len(chunk)
            if bytes_read >= next_report:
                if total_bytes:
                    pct = 100.0 * bytes_read / total_bytes
                    print(
                        f"[fetch]   {bytes_read / 1e6:.0f} MB / {total_bytes / 1e6:.0f} MB ({pct:.1f}%)",
                        file=sys.stderr,
                    )
                else:
                    print(f"[fetch]   {bytes_read / 1e6:.0f} MB", file=sys.stderr)
                next_report += 64 * (1 << 20)
    tmp.replace(dest)
    print(f"[fetch] saved {dest}", file=sys.stderr)


def _verify_md5(path: Path, expected: str) -> None:
    print(f"[fetch] verifying MD5 of {path.name}", file=sys.stderr)
    actual = _md5_of(path)
    if actual != expected:
        raise SystemExit(
            f"MD5 mismatch for {path}: expected {expected}, got {actual}. "
            "Delete the file and retry, or report a Zenodo upload corruption."
        )
    print("[fetch] MD5 ok", file=sys.stderr)


def _extract_sims(zip_path: Path) -> None:
    print(f"[fetch] extracting {zip_path.name} into {DEST_DIR}", file=sys.stderr)
    _ensure_dest()
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.namelist()
        # The archive layout is assumed to be either:
        #   sim_000/...
        #   sim_003/...
        #   sim_014/...
        # or:
        #   <root>/sim_000/...
        #   <root>/sim_003/...
        #   <root>/sim_014/...
        # We accept either by stripping a single optional leading directory.
        prefixes = {m.split("/", 1)[0] for m in members if "/" in m}
        if prefixes == set(SIM_NAMES):
            strip_prefix = ""
        elif len(prefixes) == 1 and not prefixes & set(SIM_NAMES):
            single_root = next(iter(prefixes))
            strip_prefix = single_root + "/"
            print(
                f"[fetch]   detected single archive root '{single_root}/', stripping",
                file=sys.stderr,
            )
        else:
            raise SystemExit(
                "Unexpected archive layout. Top-level entries: "
                f"{sorted(prefixes)}; expected {sorted(SIM_NAMES)} or a single wrapper directory."
            )

        for member in members:
            if not member.startswith(strip_prefix):
                continue
            rel = member[len(strip_prefix) :]
            if not rel:
                continue
            top = rel.split("/", 1)[0]
            if top not in SIM_NAMES:
                continue
            target = DEST_DIR / rel
            if member.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
    print("[fetch] extraction complete", file=sys.stderr)


def fetch_from_zenodo(*, keep_zip: bool) -> None:
    """Download the Zenodo archive, verify MD5, extract the three sims."""
    if _all_sims_present():
        print(
            f"[fetch] {DEST_DIR} already contains all three sims; nothing to do.", file=sys.stderr
        )
        return
    _ensure_dest()
    zip_path = DEST_DIR / ZENODO_FILENAME
    if not zip_path.exists():
        _download(ZENODO_URL, zip_path)
    else:
        print(f"[fetch] reusing existing archive {zip_path}", file=sys.stderr)
    _verify_md5(zip_path, ZENODO_MD5)
    _extract_sims(zip_path)
    if not keep_zip:
        zip_path.unlink()
        print(f"[fetch] removed {zip_path} (pass --keep-zip to retain)", file=sys.stderr)


def fetch_from_zip(zip_path: Path, *, keep_zip: bool) -> None:
    """Use a pre-downloaded local zip (skips the network, still verifies MD5)."""
    if not zip_path.is_file():
        raise SystemExit(f"zip file not found: {zip_path}")
    if _all_sims_present():
        print(
            f"[fetch] {DEST_DIR} already contains all three sims; nothing to do.", file=sys.stderr
        )
        return
    _verify_md5(zip_path, ZENODO_MD5)
    _extract_sims(zip_path)
    if not keep_zip and zip_path.parent == DEST_DIR:
        zip_path.unlink()


def fetch_from_local(source: Path, *, symlink: bool) -> None:
    """Copy or symlink each sim_xxx directory from a local source into DEST_DIR."""
    if not source.is_dir():
        raise SystemExit(f"source directory does not exist: {source}")
    _ensure_dest()
    for name in SIM_NAMES:
        src = source / name
        dst = DEST_DIR / name
        if not src.is_dir():
            raise SystemExit(f"expected sim directory missing from source: {src}")
        if dst.exists() or dst.is_symlink():
            print(f"[skip] {dst} already exists", file=sys.stderr)
            continue
        if symlink:
            dst.symlink_to(src.resolve(), target_is_directory=True)
            print(f"[link] {dst} -> {src}", file=sys.stderr)
        else:
            shutil.copytree(src, dst)
            print(f"[copy] {src} -> {dst}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group()
    src.add_argument(
        "--from-local",
        type=Path,
        default=None,
        metavar="DIR",
        help="Directory containing sim_000, sim_003, sim_014. Bypasses Zenodo entirely.",
    )
    src.add_argument(
        "--zip-path",
        type=Path,
        default=None,
        metavar="ZIP",
        help="Pre-downloaded Zenodo zip. Still MD5-verified before extraction.",
    )
    parser.add_argument(
        "--symlink",
        action="store_true",
        help="With --from-local, symlink instead of copy. Saves disk; breaks if source moves.",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="With Zenodo or --zip-path modes: retain the zip after extraction.",
    )
    args = parser.parse_args()

    if args.from_local is not None:
        fetch_from_local(args.from_local, symlink=args.symlink)
    elif args.zip_path is not None:
        fetch_from_zip(args.zip_path, keep_zip=args.keep_zip)
    else:
        fetch_from_zenodo(keep_zip=args.keep_zip)


if __name__ == "__main__":
    main()

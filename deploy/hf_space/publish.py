"""Publish ScrapTrust to a free Hugging Face Space (open testing). Run from the app's venv:

    D:/BMTL/app/backend/venv/Scripts/python.exe D:/BMTL/deploy/hf_space/publish.py

Needs a one-time `hf auth login` (the token is typed into a hidden prompt and kept in the Hugging Face cache, never here).

What it does:
  1. packs the code, the fitted models and the reference embeddings into bundle.tar.gz (no secrets, no company raw data,
     no user data, no tests);
  2. uploads it to a PRIVATE dataset repository <user>/scraptrust-bundle;
  3. creates the PUBLIC Docker Space <user>/scraptrust (free CPU basic) holding ONLY Dockerfile + README.md. The Dockerfile
     pins the bundle's SHA-256 and downloads it at build time with the Space secret HF_TOKEN;
  4. on first creation, sets the Space secrets SECRET_KEY (random, never stored locally) and HF_TOKEN.

Costs nothing: free Space hardware, free private repository. Nothing here selects paid hardware or storage.
Provenance caveat: the bundle carries models fitted on 9 ICP-referenced samples; the Space is for testing, not for decisions.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import secrets
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

INCLUDE = [
    "app/package.json", "app/package-lock.json", "app/index.html", "app/vite.config.js", "app/tsconfig.json", "app/src",
    "app/backend/requirements-image.lock", "app/backend/app", "app/backend/vendor", "app/backend/scripts",
    "src/realdata", "src/realmodels", "models/real",
    "app/mineral/src", "app/mineral/models", "app/mineral/data", "app/data/embeddings",
]
SKIP_NAMES = {"__pycache__", ".pytest_cache", "node_modules", ".venv", "venv"}
SKIP_SUFFIXES = {".pyc", ".log", ".tmp"}


def _skip(p: Path) -> bool:
    if any(part in SKIP_NAMES for part in p.parts):
        return True
    if p.name == ".env" or p.name.startswith(".env.") or p.suffix in SKIP_SUFFIXES:
        return True
    return False


def bundle_files(root: Path = ROOT) -> list[Path]:
    out: list[Path] = []
    for rel in INCLUDE:
        p = root / rel
        if not p.exists():
            raise SystemExit(f"missing from the repository: {rel}")
        if p.is_file():
            out.append(p)
        else:
            out.extend(f for f in sorted(p.rglob("*")) if f.is_file() and not _skip(f.relative_to(root)))
    for f in out:   # belt and braces: never ship raw company data, user data or secrets
        rel = f.relative_to(root).as_posix()
        assert not rel.startswith(("data/", "app/backend/data/", "archive/")), rel
        assert ".env" not in f.name, rel
    return out


def build_bundle(root: Path = ROOT) -> bytes:
    """Deterministic tar.gz (fixed mtimes/owners), so an unchanged tree gives the same checksum."""
    buf = io.BytesIO()
    import gzip

    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for f in bundle_files(root):
            info = tarfile.TarInfo(f.relative_to(root).as_posix())
            data = f.read_bytes()
            info.size, info.mtime, info.mode, info.uid, info.gid = len(data), 0, 0o644, 0, 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--space", default="scraptrust")
    ap.add_argument("--bundle-repo", default="scraptrust-bundle")
    ap.add_argument("--dry-run", action="store_true", help="only build the bundle and the Dockerfile locally")
    ap.add_argument("--rotate-secret", action="store_true", help="set a new SECRET_KEY (all visitors get new guest spaces)")
    args = ap.parse_args()

    data = build_bundle()
    digest = hashlib.sha256(data).hexdigest()
    print(f"bundle: {len(data) / 1e6:.1f} MB, sha256 {digest}")

    from huggingface_hub import HfApi, get_token

    token = get_token()
    if not token and not args.dry_run:
        raise SystemExit("Not signed in to Hugging Face: run `hf auth login` first.")
    api = HfApi(token=token)
    user = api.whoami()["name"] if token else "USER"
    bundle_repo, space_repo = f"{user}/{args.bundle_repo}", f"{user}/{args.space}"
    dockerfile = (HERE / "Dockerfile.template").read_text(encoding="utf-8")
    dockerfile = dockerfile.replace("__BUNDLE_REPO__", bundle_repo).replace("__BUNDLE_SHA256__", digest)
    assert "__" + "BUNDLE" not in dockerfile
    out = HERE / "build"
    out.mkdir(exist_ok=True)
    (out / "Dockerfile").write_text(dockerfile, encoding="utf-8", newline="\n")
    (out / "README.md").write_bytes((HERE / "README.space.md").read_bytes())
    if args.dry_run:
        (out / "bundle.tar.gz").write_bytes(data)
        print(f"dry run: files in {out}")
        return

    api.create_repo(bundle_repo, repo_type="dataset", private=True, exist_ok=True)
    if not api.repo_info(bundle_repo, repo_type="dataset").private:
        raise SystemExit(f"{bundle_repo} is public; make it private on huggingface.co before publishing")
    api.upload_file(path_or_fileobj=data, path_in_repo="bundle.tar.gz", repo_id=bundle_repo, repo_type="dataset",
                    commit_message=f"bundle {digest[:12]}")
    print(f"uploaded private bundle to {bundle_repo}")

    new_space = not api.repo_exists(space_repo, repo_type="space")
    if new_space:
        api.create_repo(space_repo, repo_type="space", space_sdk="docker", private=False)
    if new_space or args.rotate_secret:
        api.add_space_secret(space_repo, "SECRET_KEY", secrets.token_urlsafe(48))
    api.add_space_secret(space_repo, "HF_TOKEN", token)
    api.upload_folder(folder_path=str(out), repo_id=space_repo, repo_type="space", allow_patterns=["Dockerfile", "README.md"],
                      commit_message=f"build bundle {digest[:12]}")
    host = getattr(api.space_info(space_repo), "host", None) or f"https://{space_repo.replace('/', '-').lower()}.hf.space"
    print(f"Space building: https://huggingface.co/spaces/{space_repo}")
    print(f"Testers' link (works once the build finishes): {host}")


if __name__ == "__main__":
    sys.exit(main())

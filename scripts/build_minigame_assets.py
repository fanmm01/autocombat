#!/usr/bin/env python3
"""Generate lightweight optimized assets for the WeChat Mini Game bundle."""

from pathlib import Path

from PIL import Image


def build_assets(root: Path | None = None) -> list[Path]:
    project_root = root or Path(__file__).resolve().parent.parent
    src_logo = project_root / 'frontend' / 'public' / 'logo.png'
    out_dir = project_root / 'minigame' / 'static' / 'assets'
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []

    if src_logo.is_file():
        dst_logo = out_dir / 'logo.png'
        with Image.open(src_logo) as img:
            converted = img.convert('RGBA')
            resized = converted.resize((192, 192), Image.Resampling.LANCZOS)
            resized.save(dst_logo, format='PNG', optimize=True)
        outputs.append(dst_logo)
        print(f'Generated {dst_logo} ({dst_logo.stat().st_size} bytes)')
    else:
        raise FileNotFoundError(f'Source logo not found: {src_logo}')

    return outputs


if __name__ == '__main__':
    build_assets()

"""Regenerate the documented config template from the settings schema."""

from pathlib import Path

from tcm_control.initialise_config import render_config_template


if __name__ == "__main__":
    template = Path(__file__).with_name("config_template.toml")
    template.write_text(render_config_template(), encoding="utf-8")
    print(f"Regenerated {template}")

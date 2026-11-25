"""Generate a comment-free experiment config without overwriting an existing file."""

from pathlib import Path

from tcm_control.initialise_config import render_config_template
from tcm_utils.io_utils import prompt_input


if __name__ == "__main__":
    filename = prompt_input("Config filename (.toml): ", value_type="string")
    if not filename.lower().endswith(".toml"):
        filename += ".toml"
    config = Path(__file__).with_name(filename)
    with config.open("x", encoding="utf-8") as file:
        file.write(render_config_template(include_comments=False))
    print(f"Generated {config}")

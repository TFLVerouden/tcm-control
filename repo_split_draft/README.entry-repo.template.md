# Twente Cough Machine

![Twente Cough Machine banner](docs/assets/banner.png)

Entry repository for the Twente Cough Machine ecosystem.

This repository is intentionally thin and contains:
- pinned submodules
- onboarding docs
- shared VS Code workspace and tasks

## Repositories in this workspace

- control (tcm-control): Python host software for experiment control
- firmware (tcm-firmware): MCU firmware (PlatformIO)
- hardware: Hardware/electronics/peripherals documentation
- utils (tcm-utils): Shared Python utilities
- analysis/piv (tcm-piv): PIV analysis tooling
- analysis/dropsize (tcm-dropsize-analysis): Droplet size analysis and legacy material
- analysis/video (tcm-video-analysis): Filament/video analysis
- analysis/rheology (tcm-rheology): Rheology tooling

## Quick Start

1. Clone this repository:
   git clone https://github.com/<org>/twente-cough-machine.git
   cd twente-cough-machine

2. Initialize all submodules:
   git submodule update --init --recursive

3. Open the shared workspace:
   code twente-cough-machine.code-workspace

4. Optional: run the bootstrap script:
   ./scripts/bootstrap.sh

## Updating submodules

Update all submodules to the commits pinned by this entry repository:

- git submodule sync --recursive
- git submodule update --init --recursive

Move one submodule to latest default branch commit:

- cd control
- git checkout main
- git pull
- cd ..
- git add control
- git commit -m "Update control submodule"

## Notes

- Protocol compatibility is enforced by host and firmware via a shared integer protocol version.
- Keep host and firmware protocol versions identical.

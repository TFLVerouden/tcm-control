# Submodule Setup for twente-cough-machine

This is the exact sequence to create an entry repository that only pins submodules.

## 1. Create the entry repository first

Create an empty GitHub repository:
- Name: twente-cough-machine
- Add README: optional
- Add .gitignore: optional
- License: optional

Then clone it locally:

git clone https://github.com/TFLVerouden/twente-cough-machine.git
cd twente-cough-machine

## 2. Add submodules

git submodule add https://github.com/TFLVerouden/tcm-control.git control
git submodule add https://github.com/TFLVerouden/tcm-firmware.git firmware
git submodule add https://github.com/TFLVerouden/tcm-hardware.git hardware
git submodule add https://github.com/TFLVerouden/tcm-utils.git utils
git submodule add https://github.com/TFLVerouden/tcm-piv.git analysis/piv
git submodule add https://github.com/TFLVerouden/tcm-dropsize-analysis.git analysis/dropsize
git submodule add https://github.com/TFLVerouden/tcm-video-analysis.git analysis/video
git submodule add https://github.com/TFLVerouden/tcm-rheology.git analysis/rheology

git commit -m "Add project submodules"
git push

## 3. Set submodule tracking branches (optional but useful)

This records the preferred branch in .gitmodules.

git config -f .gitmodules submodule.control.branch main
git config -f .gitmodules submodule.firmware.branch main
git config -f .gitmodules submodule.hardware.branch main
git config -f .gitmodules submodule.utils.branch main
git config -f .gitmodules submodule.analysis/piv.branch main
git config -f .gitmodules submodule.analysis/dropsize.branch main
git config -f .gitmodules submodule.analysis/video.branch main
git config -f .gitmodules submodule.analysis/rheology.branch main

git add .gitmodules
git commit -m "Configure submodule tracking branches"
git push

## 4. Clone workflow for students

git clone https://github.com/TFLVerouden/twente-cough-machine.git
cd twente-cough-machine
git submodule update --init --recursive

## 5. Updating all submodules to latest remote branch tips

git submodule update --remote --merge --recursive
git add .
git commit -m "Bump submodule pins"
git push

## 6. Freeze teaching baseline

git tag v2026-lab1
git push origin v2026-lab1

Students then checkout that tag and update submodules:

git checkout v2026-lab1
git submodule update --init --recursive

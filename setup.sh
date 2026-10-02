#!/usr/bin/env bash
# Setup script for omarchy-rewind
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
bin_dir="${HOME}/.local/bin"

echo "==> Setting up Rewind plugin for Omarchy Shell..."

mkdir -p "${bin_dir}"

chmod +x "${script_dir}/rewind"

# Install symlinks in ~/.local/bin
ln -sf "${script_dir}/rewind" "${bin_dir}/rewind"
ln -sf "${script_dir}/rewind" "${bin_dir}/omarchy-rewind"

echo "==> Linked 'rewind' to ${bin_dir}/rewind"

# Check if ~/.config/hypr/bindings.lua exists
bindings_file="${HOME}/.config/hypr/bindings.lua"
if [[ -f "${bindings_file}" ]]; then
    if ! grep -q "rewind close" "${bindings_file}"; then
        echo ""
        echo "==> To enable keybindings, add the following to ${bindings_file}:"
        echo '    o.bind("SUPER + W", "Close window (Rewind grace)", "rewind close")'
        echo '    o.bind("SUPER + U", "Rewind closed window", "rewind restore")'
        echo '    o.bind("SUPER + CTRL + U", "Toggle Rewind", "rewind toggle")'
        echo '    o.bind("SUPER + ALT + W", "Toggle Rewind", "rewind toggle")'
        echo '    o.bind("SUPER + SHIFT + U", "Rewind settings menu", "rewind menu")'
    else
        echo "==> Keybindings already detected in ${bindings_file}"
    fi
fi

echo ""
echo "==> Setup complete! Rewind is ready to use."

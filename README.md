# Rewind Plugin for Omarchy

[![Omarchy Plugin](https://img.shields.io/badge/Omarchy-Shell%20Plugin-blue.svg)](https://omarchy.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)

**Rewind** brings instant window undo and a configurable grace period to Omarchy and Hyprland.

Accidentally closed your browser, terminal with running tasks, or editor? Rewind catches the window and holds it in hidden memory so you can bring it back instantly in the exact same state—scroll positions, running processes, and unsaved buffers intact.

---

## Preview

![Rewind Settings Preview](preview.png)

---

## Highlights & Features

- **Instant Undo Grace Period**: Intercepts `Super + W` to softly move closed applications into dedicated hidden memory (`special:rewind`) without interrupting your desktop layout.
- **Full State Preservation**: Because windows are retained in memory during the grace period, all running tasks, unsaved drafts, tabs, and terminal sessions remain intact.
- **Two Operating Modes**:
  - **Countdown Timer Mode (Default)**: Automatically terminates the application after a customizable countdown (default: 15s).
  - **Manual Indefinite Mode**: Disables the timer. The closed application remains safely in hidden memory until you restore it (`Super + U`) or close another window (which terminates the previous one and takes its place).
- **Interactive Bar Widget & Settings Menu**: Click the status bar icon or press `Super + Shift + U` to open the settings popup. Adjust grace periods (5s, 10s, 15s, 30s, 60s), switch modes, or view remaining time.
- **Native Omarchy OSD**: Displays native on-screen notifications when closing, rewinding, or toggling modes.
- **Zero Background Resource Overhead**: Ultra lightweight Python 3 architecture using only standard library modules and file locking. No persistent background daemons when idle (<0.1% CPU).

---

## Installation

### One-Command Quick Install (Recommended)

Run this single command in your terminal to install the plugin, enable it in your status bar, and configure the executable:

```bash
omarchy plugin add https://github.com/Andrewx82/omarchy-rewind.git --enable && ~/.config/omarchy/plugins/omarchy-rewind/setup.sh
```

### Manual Installation

1. Clone the repository into your Omarchy plugins directory:
   ```bash
   git clone https://github.com/Andrewx82/omarchy-rewind.git ~/.config/omarchy/plugins/omarchy-rewind
   ```

2. Run the setup script to link the `rewind` executable:
   ```bash
   ~/.config/omarchy/plugins/omarchy-rewind/setup.sh
   ```

3. Enable the plugin in your status bar:
   ```bash
   omarchy plugin enable omarchy-rewind --section right
   ```

---

## Hyprland Keybindings

To enable the keyboard shortcuts, add the following bindings to your configuration:

### Omarchy Quattro (`~/.config/hypr/bindings.lua`)

```lua
-- Rewind: Window grace period and instant undo
o.bind("SUPER + W", "Close window (Rewind grace)", "rewind close")
o.bind("SUPER + U", "Rewind closed window", "rewind restore")
o.bind("SUPER + CTRL + U", "Toggle Rewind", "rewind toggle")
o.bind("SUPER + ALT + W", "Toggle Rewind", "rewind toggle")
o.bind("SUPER + SHIFT + U", "Rewind settings menu", "rewind menu")
```

### Standard Hyprland (`~/.config/hypr/hyprland.conf`)

```ini
# Rewind: Window grace period and instant undo
bind = SUPER, W, exec, rewind close
bind = SUPER, U, exec, rewind restore
bind = SUPER CTRL, U, exec, rewind toggle
bind = SUPER ALT, W, exec, rewind toggle
bind = SUPER SHIFT, U, exec, rewind menu
```

---

## CLI Reference

The `rewind` utility can be controlled directly from the terminal or your own scripts:

| Command | Description |
|---|---|
| `rewind close` | Soft-close active window with Rewind grace period |
| `rewind restore` | Restore / rewind the last closed window to its workspace |
| `rewind toggle` | Toggle Rewind ON / OFF with native OSD |
| `rewind menu` | Open or toggle the settings popup on the status bar |
| `rewind clear` | Permanently terminate all hidden windows and clear queue |
| `rewind config --duration <sec>` | Set countdown grace duration (e.g. `rewind config --duration 30`) |
| `rewind config --disable-countdown` | Switch to manual indefinite memory mode |
| `rewind config --enable-countdown` | Switch to countdown timer mode |
| `rewind config --toggle-countdown` | Toggle between timer and manual modes |
| `rewind status` | Output JSON state for status bars and scripts |

---

## Updating & Removal

### Update

To update Rewind to the latest version:

```bash
omarchy plugin update omarchy-rewind --yes
```

### Uninstall

To uninstall Rewind and remove it from your status bar:

```bash
omarchy plugin remove omarchy-rewind --yes
rm -f ~/.local/bin/rewind ~/.local/bin/omarchy-rewind
```

---

## Dependencies & Requirements

- **Omarchy** with Omarchy Shell & Quickshell
- **Hyprland** (tested on 0.54.0+)
- **Python 3.10+** (Standard library only; zero external pip dependencies required)
- Utilities: `hyprctl`, `omarchy-shell`

---

## License

This project is licensed under the [MIT License](LICENSE).

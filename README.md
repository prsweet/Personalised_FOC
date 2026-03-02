# Personalised FOC (Fast Olympic Coding)

A Sublime Text plugin for competitive programming — run test cases, compare outputs, and parse problems from [Competitive Companion](https://github.com/jmerle/competitive-companion).

## Installation

### Prerequisites

You need a compiler/interpreter for your language:

| Platform | C++ | Python | Java |
|----------|-----|--------|------|
| **macOS** | `xcode-select --install` | Comes pre-installed (`python3`) | [Download JDK](https://adoptium.net/) |
| **Linux** | `sudo apt install g++` (Debian/Ubuntu) | `sudo apt install python3` | `sudo apt install default-jdk` |
| **Windows** | Install [MinGW-w64](https://www.mingw-w64.org/) and add to PATH | [Download Python](https://python.org) (check "Add to PATH") | [Download JDK](https://adoptium.net/) |

> **⚠️ Most common issue on macOS:** If `g++` is not found, run `xcode-select --install` in Terminal.

### Install the Plugin

1. **Clone this repo** into your Sublime Text `Packages` directory:

   | Platform | Packages Directory |
   |----------|--------------------|
   | **macOS** | `~/Library/Application Support/Sublime Text/Packages/` |
   | **Linux** | `~/.config/sublime-text/Packages/` |
   | **Windows** | `%APPDATA%\Sublime Text\Packages\` |

   ```bash
   cd "<Packages directory from above>"
   git clone https://github.com/prsweet/Personalised_FOC.git Personalised_FOC
   ```

   > **Important:** The folder must be named exactly `Personalised_FOC`.

2. **Restart Sublime Text** after cloning.

3. **Verify:** Open a `.cpp` file and press `Ctrl+B` (or `Cmd+B` on macOS... actually it's `Ctrl+B` on all platforms). A test panel should appear on the right.

## Usage

### Keybindings

| Action | macOS | Linux/Windows |
|--------|-------|---------------|
| **Run tests** | `Ctrl+B` | `Ctrl+B` |
| **New test case** | `Ctrl+Enter` (in test panel) | `Ctrl+Enter` |
| **Run all tests** | `Cmd+'` | `Ctrl+'` |
| **Open problem file** | `Cmd+Shift+O` | `Ctrl+Shift+O` |
| **Reload companion** | `Cmd+Shift+R` | `Ctrl+Shift+R` |

### Competitive Companion Integration

1. Install the [Competitive Companion](https://github.com/jmerle/competitive-companion) browser extension
2. Open Sublime Text with a project folder
3. Click the Competitive Companion icon on a problem page
4. The plugin auto-creates the source file with your template and loads test cases

### Test Case UI

- **Green border** = Passed ✓
- **Red border** = Wrong Answer ✗
- **Orange border** = Runtime Error / Time Limit Exceeded
- Click **▶/▼** to expand/collapse test case details
- Use **Run**, **Edit**, **Delete** buttons per test case
- Use **New Case** and **Run All** at the bottom

## Settings

Open via Command Palette → `FastOlympicCoding: Open Settings`

Key settings you can override in your User settings file:

```json
{
    "stress_time_limit_seconds": 4,
    "close_sidebar": false,
    "companion_listener_port": 10043,
    "default_language_extension": "cpp"
}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `g++: command not found` (macOS) | Run `xcode-select --install` in Terminal |
| `g++: command not found` (Linux) | `sudo apt install g++` or `sudo pacman -S gcc` |
| `g++: command not found` (Windows) | Install MinGW-w64 and add `bin` folder to system PATH |
| Plugin not loading | Ensure folder is named exactly `Personalised_FOC` inside `Packages/` |
| Companion not receiving problems | Check port 10043 is free; restart Sublime Text |
| Tests not saving | Ensure your project folder is writable |

# Build Tools

Scripts for creating standalone executable bundles using PyInstaller.

## Scripts

### `build_app.sh` - macOS/Linux Build Script

Creates a macOS `.app` bundle with all dependencies included.

**Usage:**
```bash
./tools/build_app.sh
```

**Output:**
- `dist/OneLogin Migration Tool.app` - macOS application bundle

**What it does:**
1. Detects or activates Python virtual environment
2. Installs all monorepo packages (core, cli, gui, layered_credentials)
3. Installs PyInstaller if not present
4. Cleans previous builds
5. Runs PyInstaller with `onelogin-migration-tool.spec`
6. Creates signed `.app` bundle (ad-hoc signature)

**Requirements:**
- macOS 10.13+ (build machine)
- Python 3.10-3.13
- Virtual environment in `.venv/` (or currently activated)

**Post-Build:**
- Run: `open "dist/OneLogin Migration Tool.app"`
- Create DMG: See instructions in main README
- Code sign: Requires Apple Developer ID certificate

---

### `build_app.bat` - Windows Build Script

Creates a Windows `.exe` executable with all dependencies included.

**Usage:**
```cmd
tools\build_app.bat
```

**Output:**
- `dist\OneLogin Migration Tool.exe` - Windows executable
- `dist\OneLogin Migration Tool\` - Support files directory

**What it does:**
1. Installs all monorepo packages (core, cli, gui, layered_credentials)
2. Installs PyInstaller if not present
3. Cleans previous builds
4. Runs PyInstaller with `onelogin-migration-tool.spec`
5. Creates executable with embedded icon

**Requirements:**
- Windows 10+ (build machine)
- Python 3.10-3.13
- Activated virtual environment (recommended)

**Post-Build:**
- Run: `"dist\OneLogin Migration Tool.exe"`
- Create installer: Use Inno Setup (see main README)

---

## PyInstaller Configuration

The build configuration is defined in `onelogin-migration-tool.spec` at the project root.

**Key Features:**
- **Entry Point:** `packages/gui/src/onelogin_migration_gui/main.py`
- **Bundled Assets:**
  - OneLogin logos (black/white variants)
  - App icons (`.icns` for Mac, `.ico` for Windows)
  - SQLite connector catalog database
  - PySide6 Qt plugins and resources
- **Hidden Imports:** PySide6, typer, rich, requests, yaml, etc.
- **Platform Detection:** Automatically creates `.app` on macOS, `.exe` on Windows
- **Console Mode:** Disabled (GUI-only, no terminal window)

**Customization:**

To modify the build configuration, edit `onelogin-migration-tool.spec`:

```python
# Add additional data files
datas = [
    ('path/to/file', 'destination/path'),
]

# Add hidden imports
hiddenimports = [
    'your.module.here',
]

# Change app name/version
app = BUNDLE(
    coll,
    name='Your App Name.app',
    info_plist={
        'CFBundleShortVersionString': '1.0.0',
    }
)
```

---

## Troubleshooting

### "PyInstaller not found"
**Solution:** Install PyInstaller:
```bash
pip install pyinstaller
```

### "ModuleNotFoundError" during build
**Solution:** Ensure all packages are installed:
```bash
./scripts/dev-install.sh
```

### macOS "App is damaged" error
**Solution:** Remove quarantine attribute:
```bash
xattr -cr "dist/OneLogin Migration Tool.app"
```

Or properly code sign the app.

### Windows Defender blocks executable
**Solution:** This is expected for unsigned executables. To distribute:
1. Code sign with a valid certificate
2. Or instruct users to allow in Windows Defender

### Build fails with "permission denied"
**Solution (macOS/Linux):** Make script executable:
```bash
chmod +x tools/build_app.sh
```

### Large executable size (~150-200MB)
This is normal for bundled Python apps with Qt/PySide6. The bundle includes:
- Python interpreter
- All dependencies (PySide6, numpy, cryptography, etc.)
- Qt plugins and resources

**To reduce size:**
- Remove unused Qt modules from `hiddenimports`
- Use UPX compression (enabled by default)
- Exclude unnecessary packages

---

## Build Output Structure

### macOS
```
dist/
└── OneLogin Migration Tool.app/
    └── Contents/
        ├── Info.plist          # App metadata
        ├── MacOS/              # Executable
        ├── Resources/          # Icons, assets
        └── Frameworks/         # Python, Qt, dependencies
```

### Windows
```
dist/
└── OneLogin Migration Tool/
    ├── OneLogin Migration Tool.exe  # Main executable
    ├── base_library.zip             # Python standard library
    ├── _internal/                   # Dependencies, Qt plugins
    └── onelogin_migration_gui/      # Assets
```

---

## CI/CD Integration

### GitHub Actions Example

**macOS:**
```yaml
- name: Build macOS App
  run: ./tools/build_app.sh

- name: Upload Artifact
  uses: actions/upload-artifact@v3
  with:
    name: macos-app
    path: dist/OneLogin Migration Tool.app
```

**Windows:**
```yaml
- name: Build Windows App
  run: tools\build_app.bat

- name: Upload Artifact
  uses: actions/upload-artifact@v3
  with:
    name: windows-exe
    path: dist/OneLogin Migration Tool.exe
```

---

## Distribution

### macOS
1. **DMG Creation:**
   ```bash
   hdiutil create -volname "OneLogin Migration Tool" \
     -srcfolder "dist/OneLogin Migration Tool.app" \
     -ov -format UDZO \
     "dist/OneLogin-Migration-Tool.dmg"
   ```

2. **Code Signing:**
   ```bash
   codesign --deep --force --verify --verbose \
     --sign "Developer ID Application: Your Name" \
     "dist/OneLogin Migration Tool.app"
   ```

3. **Notarization** (optional, for Gatekeeper bypass):
   ```bash
   xcrun notarytool submit "dist/OneLogin-Migration-Tool.dmg" \
     --apple-id "your@email.com" \
     --team-id "YOUR_TEAM_ID" \
     --password "app-specific-password"
   ```

### Windows
1. **Installer Creation with Inno Setup:**
   - Download [Inno Setup](https://jrsoftware.org/isinfo.php)
   - Create `installer.iss` script
   - Point to `dist\OneLogin Migration Tool.exe`
   - Build installer

2. **Code Signing:**
   ```cmd
   signtool sign /f certificate.pfx /p password /t http://timestamp.digicert.com "dist\OneLogin Migration Tool.exe"
   ```

---

## See Also
- Main README: [../README.md](../README.md#building-standalone-executables)
- PyInstaller Docs: https://pyinstaller.org/
- PySide6 Deployment: https://doc.qt.io/qtforpython/deployment.html

# WildCatcher — Complete Setup Guide
# From your existing folder to GitHub releases

---

## STEP 0: What you need from your original folder

Your final repo should look like this. Items marked ✅ are ALREADY in your folder.
Items marked 🆕 come from this project_setup.zip.
Items marked 🔄 you need to REPLACE with the version I gave you.

```
WildCatcher_app/
│
├── 🆕 .github/workflows/release.yml     ← Auto-build workflow
├── 🆕 .gitignore
├── 🆕 .gitattributes                     ← Git LFS for .pt files
├── 🆕 wildcatcher.spec                   ← PyInstaller config (replaces old .spec)
├── 🆕 requirements-base.txt
├── 🆕 requirements-win-gpu.txt
├── 🆕 requirements-mac.txt
├── 🆕 SETUP_INSTRUCTIONS.md              ← This file
│
├── 🔄 detector_animales_diego.py          ← Use the UPDATED version from me!
│
├── ✅ process_images.py
├── ✅ load_detector.py
├── ✅ video_player.py
├── ✅ detector_AI_model.pt                ← 268 MB (tracked by Git LFS)
├── ✅ prec90rec93f191.pt                  ← 270 MB (tracked by Git LFS)
├── ✅ assets/                             ← Icons and flags
├── ✅ yolov5/                             ← Detection code
└── ✅ vlc/                                ← VLC libraries (Windows)
```

### ❌ DELETE these from your folder BEFORE committing:
```
__pycache__/                ← Python cache
build/                      ← Old PyInstaller output
venv/                       ← Your local Python environment
.python-version             ← Dev tool config
app.log                     ← Runtime log
license.wcl                 ← User-specific license (NEVER commit this!)
inno_setup.iss              ← Old Inno Setup installer (replaced by GitHub Actions)
detector_animales_diego.spec ← Old spec file (replaced by wildcatcher.spec)
requirements.txt            ← Old requirements (replaced by the 3 new files)
```

---

## STEP 1: Clean up your folder

Open PowerShell in your project folder and run:

```powershell
cd C:\path\to\your\WildCatcher_folder

# Delete files/folders that should NOT be in the repo
Remove-Item -Recurse -Force __pycache__ -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force venv -ErrorAction SilentlyContinue
Remove-Item -Force .python-version -ErrorAction SilentlyContinue
Remove-Item -Force app.log -ErrorAction SilentlyContinue
Remove-Item -Force license.wcl -ErrorAction SilentlyContinue
Remove-Item -Force inno_setup.iss -ErrorAction SilentlyContinue
Remove-Item -Force detector_animales_diego.spec -ErrorAction SilentlyContinue
Remove-Item -Force requirements.txt -ErrorAction SilentlyContinue
```

---

## STEP 2: Add the new files

1. Extract `project_setup.zip`
2. Copy EVERYTHING from inside the extracted folder into your project root:
   - The `.github` folder (contains `workflows/release.yml`)
   - `.gitignore`
   - `.gitattributes`
   - `wildcatcher.spec`
   - `requirements-base.txt`
   - `requirements-win-gpu.txt`
   - `requirements-mac.txt`
   - `SETUP_INSTRUCTIONS.md`

3. Replace `detector_animales_diego.py` with the updated version I gave you

---

## STEP 3: Install Git and Git LFS (if not already installed)

### Windows:
1. Download Git: https://git-scm.com/download/win → install with defaults
2. Download Git LFS: https://git-lfs.com → run the installer

Verify both work:
```powershell
git --version
git lfs --version
```

---

## STEP 4: Push to GitHub

Run these commands ONE BY ONE in PowerShell, inside your project folder:

```powershell
# 1. Initialize git repo
git init

# 2. Set up Git LFS for large files
git lfs install
git lfs track "*.pt"
git lfs track "*.pth"

# 3. Connect to your GitHub repo
git remote add origin https://github.com/Theego99/WildCatcher_app.git

# 4. Set branch name
git branch -M main

# 5. Stage ALL files
git add .

# 6. Review what will be committed (make sure no license.wcl, venv, etc.)
git status

# 7. Commit
git commit -m "Initial commit: WildCatcher with cross-platform support"

# 8. Push (this will upload ~540 MB of .pt files via LFS — may take a few minutes)
git push -u origin main --force
```

### If git push asks for authentication:
GitHub no longer accepts passwords. You need a **Personal Access Token**:
1. Go to https://github.com/settings/tokens
2. Click "Generate new token (classic)"
3. Check the `repo` box (full control of private repositories)
4. Click "Generate token" and COPY it immediately
5. When `git push` asks for password, paste the token

---

## STEP 5: Verify on GitHub

Go to https://github.com/Theego99/WildCatcher_app

Check that:
- [ ] `detector_animales_diego.py` is there (96 KB)
- [ ] `assets/` folder exists with icons
- [ ] `yolov5/` folder exists
- [ ] `vlc/` folder exists
- [ ] Click on `detector_AI_model.pt` — it should say **"Stored with Git LFS"**
- [ ] Click on `prec90rec93f191.pt` — same LFS message
- [ ] `.github/workflows/release.yml` exists
- [ ] NO `license.wcl`, `__pycache__`, `build/`, `venv/`

---

## STEP 6: Create your first release

```powershell
git tag v1.0.0
git push origin v1.0.0
```

Now go to: https://github.com/Theego99/WildCatcher_app/actions

You'll see the "Build & Release" workflow running. It builds 3 versions:
- Windows (NVIDIA CUDA GPU) → `WildCatcher-Windows-x64.zip`
- macOS (Apple MPS GPU) → `WildCatcher-macOS-arm64.zip`
- Linux (NVIDIA CUDA GPU) → `WildCatcher-Linux-x64.tar.gz`

When done (~15-20 min), find downloads at:
https://github.com/Theego99/WildCatcher_app/releases

---

## STEP 7: Future updates

Whenever you change code:

```powershell
git add .
git commit -m "Describe what you changed"
git push
```

When ready to release a new version:
```powershell
git tag v1.1.0
git push origin v1.1.0
# → Automatically builds for all 3 platforms
```

---

## Troubleshooting

### "fatal: remote origin already exists"
```powershell
git remote remove origin
git remote add origin https://github.com/Theego99/WildCatcher_app.git
```

### "error: failed to push some refs" / repo not empty
If your GitHub repo already has files (like a README):
```powershell
git push -u origin main --force
```

### Git LFS: "batch request: Git LFS is not enabled on this server"
Go to your repo Settings on GitHub → make sure LFS is enabled.

### Push is very slow
Your two .pt files are ~538 MB total. First push takes 5-15 min depending
on your internet speed. After that, only changed files are uploaded.

### GitHub Actions build fails
Check logs at https://github.com/Theego99/WildCatcher_app/actions
Most common: missing hidden imports → edit `wildcatcher.spec` hiddenimports list.

### macOS users get "WildCatcher.app is damaged"
They need to run:
```bash
xattr -cr /path/to/WildCatcher.app
```

### App works locally but crashes in release build
Test locally first:
```powershell
pip install pyinstaller
pyinstaller wildcatcher.spec
cd dist\WildCatcher
.\WildCatcher.exe
```

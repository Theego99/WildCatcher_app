# Installing WildCatcher / WildCatcher のインストール

The app is safe but not yet code-signed, so your operating system shows a
one-time warning. Here is how to get past it. You only do this **once**.

このアプリは安全ですが、まだコード署名されていないため、OS が一度だけ警告を表示
します。以下の手順で進めてください。**最初の1回だけ**必要です。

---

## Windows

1. Double-click **`WildCatcher_v2.1.0_Setup.exe`**.
2. If a blue **"Windows protected your PC"** window appears:
   - Click **More info**.
   - Click **Run anyway**.
3. Follow the installer, then launch **WildCatcher** from the Start menu.

**日本語:**
1. **`WildCatcher_v2.1.0_Setup.exe`** をダブルクリックします。
2. 青い「**WindowsによってPCが保護されました**」画面が出たら：
   - 「**詳細情報**」をクリック。
   - 「**実行**」をクリック。
3. インストーラーに従い、スタートメニューから **WildCatcher** を起動します。

---

## macOS (Apple Silicon)

1. Unzip the download → you get **`WildCatcher.app`**. Move it to **Applications**.
2. The first time, **right-click** (or Control-click) the app → **Open** →
   **Open** again in the dialog. (A normal double-click is blocked the first time.)
3. If it says the app is **"damaged"**, open **Terminal** and run:
   ```bash
   xattr -dr com.apple.quarantine /Applications/WildCatcher.app
   ```
4. **Video playback** needs [VLC](https://www.videolan.org/vlc/) installed;
   detection, classification and reports work without it.

**日本語:**
1. ダウンロードを解凍すると **`WildCatcher.app`** ができます。**アプリケーション**に移動します。
2. 初回は、アプリを**右クリック**（またはControlキーを押しながらクリック）→「**開く**」→
   ダイアログでもう一度「**開く**」。（初回は通常のダブルクリックではブロックされます。）
3. 「**壊れている**」と表示される場合は、**ターミナル**で次を実行：
   ```bash
   xattr -dr com.apple.quarantine /Applications/WildCatcher.app
   ```
4. **動画再生**には [VLC](https://www.videolan.org/vlc/) が必要です。検出・分類・レポート出力はVLCなしで動作します。

---

## First launch / 初回起動

- Accept the license agreement (once).
- The app starts a **free 14-day trial** automatically, or enter the license key
  you were given. To activate: click the logo → paste your key → **Activate**.

- 使用許諾契約に同意します（初回のみ）。
- アプリは自動的に**14日間の無料トライアル**を開始します。または、受け取った
  ライセンスキーを入力してください。有効化：ロゴをクリック → キーを貼り付け → 「**有効化**」。

---

*Having trouble? Contact your vendor / ご不明な点は販売元までご連絡ください.*

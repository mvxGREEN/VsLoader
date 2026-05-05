"""
VSCO Downloader for iOS
"""

import toga
import asyncio
import queue
from asyncio import TaskGroup
import io
import json
import contextlib
import re
from urllib.parse import unquote
import random
import sys
import os
import requests
from io import BytesIO
from pathlib import Path
from toga.validators import MinLength, StartsWith, Contains
from toga.style import Pack
from toga.style.pack import COLUMN, ROW, LEFT, CENTER, RIGHT


class TerminateTaskGroup(Exception):
    """Exception raised to terminate a task group."""

async def force_terminate_task_group():
    """Used to force termination of a task group."""
    raise TerminateTaskGroup()


# NOTE: currently adding trailing slash
def get_dest_path():
    # check OS
    if sys.platform == 'ios':
        print("Running on iOS")
        return os.path.join(os.path.expanduser('~'), 'Documents') + "/"
    elif sys.platform == 'win32':
        print("Running on Windows.")
        return "C:\\Users\\maxwe\\VsLoader\\"
    elif sys.platform == 'android':
        print("Running on Android.")
        return "/storage/emulated/0/Documents/"
    elif sys.platform == 'darwin':
        print("Running on macOS.")
        return str(Path.home() / "Downloads") + "/"
    else:
        print(f"Running on a different platform: {sys.platform}\nReturning default path_out (windows)")
        return "C:\\Users\\maxwe\\StudioProjects\\vsloader\\"


def sanitize_filename(filename):
    """Removes or replaces sensitive characters from a filename.

    Args:
        filename (str): The filename to sanitize.

    Returns:
        str: The sanitized filename.
    """

    # 1. Remove or replace characters that are invalid across platforms
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1F]', '_', filename)

    # 2. Remove or replace characters that might cause issues with specific OS
    filename = filename.replace(' ', '_')  # replace spaces
    filename = filename.strip('. ')  # Remove leading/trailing spaces and dots

    # 3. Remove potentially problematic characters
    filename = re.sub(r'[,;!@#\$%^&()+]', '', filename)

    # 4. Normalize Unicode characters
    filename = filename.encode('ascii', 'ignore').decode('ascii')

    return filename


def validate_url(value):
    """Custom Toga validator to check for valid VSCO URLs."""
    if not value:
        return  # Allow empty
    
    # Strict regex for VSCO domains only (vsco.co and vs.co)
    url_pattern = re.compile(r"^(?:https?://)?(?:www\.)?(?:vsco\.co|vs\.co)(?:/.*)?$", re.IGNORECASE)
    
    if not url_pattern.match(value):
        raise ValueError("Please paste a valid VSCO link (vsco.co or vs.co)")


async def extract_vsco_info(vsco_url, resolution):
    """
    Extracts VSCO media directly from HTML using curl_cffi
    to bypass Cloudflare TLS fingerprinting blocks.
    """
    print(f"Starting HTML extraction for: {vsco_url}")
    
    # delay
    await asyncio.sleep(0.043)
    
    def extract():
        target_url = vsco_url
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        # The 'impersonate' argument handles all the complex TLS spoofing
        # and header generation automatically!
        res = requests.get(target_url, headers=headers, timeout=15, allow_redirects=True)
        
        target_url = res.url.split('?')[0]
        html = res.text
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # Fallback shortlink resolution
        if "vs.co/" in target_url:
            canonical_match = re.search(r'(https://vsco\.co/[^"\'\s>]+)', html)
            if canonical_match:
                target_url = canonical_match.group(1).split('?')[0]
                # Re-fetch with impersonation
                res = requests.get(target_url, headers=headers, timeout=15)
                html = res.text

        if res.status_code == 403:
            raise Exception("Cloudflare is still blocking the request. Your IP may be temporarily flagged.")

        # --- The rest of your regex extraction logic stays exactly the same ---
        download_url = ""
        thumbnail_url = ""
        ext = "jpg"
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        
        video_match = re.search(r'property="og:video" content="([^"]+)"', html)
        if video_match:
            v_url = video_match.group(1).replace("&amp;", "&")
            v_res = requests.get(v_url, headers=headers, timeout=15)
            v_html = v_res.text
            
            mux_match = re.search(r'(stream\.mux\.com[^"]+)', v_html)
            if mux_match:
                download_url = "https://" + mux_match.group(1).replace("\\u002F", "/")
                ext = "mp4"
            else:
                mp4_match = re.search(r'(https://[^"]+\.mp4)', v_html)
                if mp4_match:
                    download_url = mp4_match.group(1)
                    ext = "mp4"

        if not download_url:
            image_match = re.search(r'property="og:image" content="([^"]+)"', html)
            if image_match:
                download_url = image_match.group(1).split('?')[0]
                ext = "jpg"

        if ext == "mp4":
            poster_match = re.search(r'property="og:image" content="([^"]+)"', html)
            if poster_match:
                thumbnail_url = poster_match.group(1)
        else:
            thumbnail_url = download_url

        if not download_url:
            raise Exception("Could not find media URLs in the page HTML.")

        title_match = re.search(r'<title>(.*?)</title>', html)
        title = "vsco_media"
        if title_match:
            raw_title = title_match.group(1)
            parts = raw_title.split("|")
            title = parts[-2].strip() if len(parts) >= 3 else (parts[0].strip() if parts else raw_title.strip())
            title = re.sub(r'[^a-zA-Z0-9_\-]', '', title.replace(' ', '_'))
            if not title:
                title = "vsco_download"

        return {
            "title": title,
            "ext": ext,
            "thumbnail": thumbnail_url,
            "download_url": download_url
        }

    return await asyncio.to_thread(extract)


async def dl_vsco_async(download_url, out_path, filename, ext, progress_hook):
    """Downloads the direct media URL natively on iOS."""
    print(f"starting dl_vsco_async for direct URL: {download_url}")
    
    await asyncio.sleep(0.043)
    
    def download():
        import sys
        import os
        os.makedirs(out_path, exist_ok=True)
        
        # --- NEW: File Collision Prevention ---
        base_name = filename
        dest = os.path.join(out_path, f"{base_name}.{ext}")
        counter = 1
        
        # Keep incrementing the counter until we find a filename that doesn't exist
        while os.path.exists(dest):
            dest = os.path.join(out_path, f"{base_name}_{counter}.{ext}")
            counter += 1
        # --------------------------------------
        
        def fetch_data(url_str):
            if sys.platform == 'ios':
                import ctypes
                from rubicon.objc import ObjCClass
                NSURL = ObjCClass('NSURL')
                NSMutableURLRequest = ObjCClass('NSMutableURLRequest')
                NSURLConnection = ObjCClass('NSURLConnection')
                
                url_obj = NSURL.URLWithString_(str(url_str))
                req = NSMutableURLRequest.requestWithURL_(url_obj)
                req.setValue_forHTTPHeaderField_(
                    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                    "User-Agent"
                )
                
                data = NSURLConnection.sendSynchronousRequest_returningResponse_error_(req, None, None)
                if data is None:
                    raise Exception(f"Native iOS download blocked or failed: {url_str}")
                
                # Extract Python bytes from NSData
                return ctypes.string_at(data.bytes, data.length)
            else:
                import urllib.request
                req = urllib.request.Request(
                    url_str,
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                )
                with urllib.request.urlopen(req, timeout=15) as response:
                    return response.read()

        is_playlist = download_url.endswith(".m3u8")

        # --- DIRECT FILE DOWNLOAD (Images & Direct MP4s) ---
        if not is_playlist:
            print(f"Downloading direct media file to {dest}...")
            progress_hook({'status': 'downloading'})
            
            content = fetch_data(download_url)
            with open(dest, 'wb') as f:
                f.write(content)
                            
            progress_hook({'status': 'finished'})

        # --- VIDEO PLAYLIST DOWNLOAD (M3U8 Chunks) ---
        else:
            print(f"Downloading video stream manually to {dest}...")
            progress_hook({'status': 'downloading'})
            
            m3u8_content = fetch_data(download_url).decode('utf-8')
            lines = m3u8_content.split('\n')
            base_url = download_url.rsplit('/', 1)[0] + '/'
            ts_urls = []
            
            for line in lines:
                if line and not line.startswith('#'):
                    if not line.startswith('http'):
                        ts_urls.append(base_url + line)
                    else:
                        ts_urls.append(line)
                        
            total_chunks = len(ts_urls)
            with open(dest, 'wb') as outfile:
                for i, ts_url in enumerate(ts_urls):
                    chunk_data = fetch_data(ts_url)
                    outfile.write(chunk_data)
                    progress_hook({
                        'status': 'downloading',
                        'fragment_index': i + 1,
                        'fragment_count': total_chunks
                    })

            progress_hook({'status': 'finished'})

    await asyncio.to_thread(download)


async def create_progress_hook(progress_bar):
    progress_bar.style.visibility = 'visible'
    # progress_bar.max = 100
    progress_bar.start()

    def progress_hook(d):
        if d['status'] == 'downloading':
            if d.get('total_bytes') and d.get('downloaded_bytes'):
                percent_int = int((d['downloaded_bytes'] / d['total_bytes']) * 100)
                
                # Safely update the UI on the main thread
                progress_bar.app.loop.call_soon_threadsafe(
                    lambda: setattr(progress_bar, 'value', percent_int)
                )
            elif d.get('fragment_index') and d.get('fragment_count'):
                # calculate progress
                percent_float = (d['fragment_index'] / d['fragment_count']) * 100
                percent_int = int(percent_float)
                # update progress
                # progress_bar.value = percent_int
                print(f"Download Progress: {percent_int}%")
            else:
                # indeterminate progress
                print("Downloading...but missing progress info")

        elif d['status'] == 'finished':
            print("download finished!")
            # progress_bar.value = 100
        elif d['status'] == 'error':
            print("download error!")

            # TODO show error message

    return progress_hook


class VsLoader(toga.App):
    def startup(self):
        # register fonts
        toga.Font.register("FiraSans", "resources/FiraSans-Regular.ttf")
        toga.Font.register("FiraSansExtraLight", "resources/FiraSans-ExtraLight.ttf")
        toga.Font.register("FiraSansBold", "resources/FiraSans-Bold.ttf")
        toga.Font.register("Gotu", "resources/Gotu-Regular.ttf")

        # show init layout
        self.show_init_layout()

    def show_init_layout(self):
        print("show_init_layout")
        self.main_box = toga.Box(direction=COLUMN)

        # init webview
        self.main_webview = toga.WebView(
            url="https://www.google.com",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            style=Pack(width=1, height=1))
        self.main_webview.style.visibility = 'hidden'
        self.main_box.add(self.main_webview)

        # hint
        hint_label = toga.Label(
            "Paste URL:",
            font_family="Gotu",
            font_size=14,
            margin=(16,4,2,20),
        )
        self.hint_box = toga.Box(children=[hint_label])

        # url textinput
        self.url_input = toga.TextInput(direction=ROW,
                                        on_confirm=self.load_input,
                                        on_change=self.input_change,
                                        flex=1,
                                        validators=[validate_url],
                                        style=Pack(
                                            height=48,
                                            margin_left=8))
        # paste button
        self.paste_button = toga.Button(
            icon=toga.Icon("resources/bolt_512"),
            on_press=self.paste_and_load,
            margin=(4,0,0,8),
            style=Pack(width=48) # Forces the button to remain comfortable size
        )
        self.paste_button.style.visibility = 'visible'

        # --- iOS Native UI Enhancements ---
        import sys
        if sys.platform == 'ios':
            try:
                from rubicon.objc import ObjCClass
                UIImage = ObjCClass("UIImage")
                UIColor = ObjCClass("UIColor")
                UIImageSymbolConfiguration = ObjCClass("UIImageSymbolConfiguration")
                
                # Access the underlying native iOS UIButton
                native_btn = self.paste_button._impl.native
                
                # 1. Create a configuration to scale up the SF Symbol.
                # A point size of ~28.0 matches standard iOS text inputs well.
                symbol_config = UIImageSymbolConfiguration.configurationWithPointSize(28.0)
                
                # 2. Apply the configuration when loading the vector image
                bolt_image = UIImage.systemImageNamed("bolt.fill", withConfiguration=symbol_config)
                
                # 3. Create a yellow version for the active press state
                yellow_color = UIColor.systemYellowColor()
                yellow_bolt = bolt_image.imageWithTintColor(yellow_color, renderingMode=1)
                
                # 4. Apply states to the native button
                native_btn.setImage(bolt_image, forState=0)
                native_btn.setImage(yellow_bolt, forState=1)
                native_btn.setTitle("", forState=0)
                
            except Exception as e:
                print(f"Could not apply iOS native button styling: {e}")
        # ----------------------------------
        
        self.url_box = toga.Box(margin=(0, 8))
        self.url_box.add(self.url_input)
        self.url_box.add(self.paste_button)

        # main box
        self.main_box.add(self.hint_box)
        self.main_box.add(self.url_box)

        # preview box
        self.preview_box = toga.Box(direction=COLUMN)
        self.main_box.add(self.preview_box)

        # image box
        # We use a fixed width and height (340x340) to force a perfect square
        # that fills up most of an iPhone screen, and center it in the box.
        self.image_view = toga.ImageView(image=None, style=Pack(width=340, height=340))
        self.image_box = toga.Box(children=[self.image_view], style=Pack(direction=COLUMN, alignment=CENTER, padding_top=16, padding_bottom=16))
        self.preview_box.add(self.image_box)

        # --- iOS Native Image Styling (Aspect Fill & Rounded Corners) ---
        import sys
        if sys.platform == 'ios':
            try:
                # Access the underlying native iOS UIImageView
                native_img_view = self.image_view._impl.native
                
                # UIViewContentModeScaleAspectFill (2) forces the image to fill the square and crop the excess
                native_img_view.contentMode = 2
                
                # clipsToBounds ensures the cropped excess and corners are visually hidden
                native_img_view.clipsToBounds = True
                
                # Apply a smooth continuous Apple-style corner radius
                native_img_view.layer.cornerRadius = 16.0
                
            except Exception as e:
                print(f"Could not apply iOS native image styling: {e}")
        # ----------------------------------------------------------------

        # filename box
        self.filename_input_label = toga.Label(
            "Filename:",
            font_family="Gotu",
            margin=(12, 4, 8, 12)
        )
        self.filename_input = toga.TextInput(
            margin=(8, 12, 8, 4),
            direction=ROW,
            flex=1)
        filename_box = toga.Box(direction=ROW)
        filename_box.add(self.filename_input_label)
        filename_box.add(self.filename_input)
        self.preview_box.add(filename_box)

        # download box
        self.download_button = toga.Button(
            "Download",
            on_press=self.download_input,
            margin=8,
        )
        download_box = toga.Box(children=[self.download_button], direction=COLUMN)
        self.preview_box.add(download_box)

        # progress box
        self.progress = toga.ProgressBar(max=None, direction=ROW, flex=1)
        progress_box = toga.Box(children=[self.progress], direction=COLUMN)
        self.preview_box.add(progress_box)
        self.progress.style.visibility = 'hidden'

        # hide preview widgets
        self.image_view.style.visibility = 'hidden'
        self.filename_input_label.style.visibility = 'hidden'
        self.filename_input.style.visibility = 'hidden'
        self.download_button.style.visibility = 'hidden'

        # main window
        self.main_window = toga.MainWindow(title="VsLoader")
        self.main_window.content = self.main_box
        self.main_window.show()

    def show_loading_layout(self):
        print("show_loading_layout")

        # disable url textinput
        self.url_input.enabled = False
        self.filename_input.enabled = False

        # hide preview widgets EXCEPT the download button
        self.image_view.style.visibility = 'hidden'
        self.filename_input_label.style.visibility = 'hidden'
        self.filename_input.style.visibility = 'hidden'

        # update download button for the initial loading state
        self.download_button.style.visibility = 'visible'
        self.download_button.text = "Loading..."
        self.download_button.enabled = False

        # update paste button
        self.paste_button.enabled = False

        # show indeterminate progressbar
        self.progress.max = None
        self.progress.style.visibility = 'visible'
        self.progress.start()

    async def show_preview_layout(self, filename, thumbnail_url):
        print("show_preview_layout")

        if thumbnail_url.endswith(".webp"):
            thumbnail_url = thumbnail_url.replace("vi_webp", "vi")
            thumbnail_url = thumbnail_url.replace(".webp", ".jpg")

        try:
            print(f"loading thumbnail_url: {thumbnail_url}")

            def fetch_thumbnail():
                import sys
                if sys.platform == 'ios':
                    import ctypes
                    from rubicon.objc import ObjCClass
                    NSURL = ObjCClass('NSURL')
                    NSMutableURLRequest = ObjCClass('NSMutableURLRequest')
                    NSURLConnection = ObjCClass('NSURLConnection')
                    
                    url_obj = NSURL.URLWithString_(str(thumbnail_url))
                    req = NSMutableURLRequest.requestWithURL_(url_obj)
                    
                    req.setValue_forHTTPHeaderField_(
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                        "User-Agent"
                    )
                    
                    data = NSURLConnection.sendSynchronousRequest_returningResponse_error_(req, None, None)
                    
                    if data is None:
                        raise Exception("Native iOS download blocked or failed for thumbnail.")
                    
                    return ctypes.string_at(data.bytes, data.length)
                else:
                    import urllib.request
                    req = urllib.request.Request(
                        thumbnail_url,
                        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                    )
                    with urllib.request.urlopen(req, timeout=15) as response:
                        return response.read()

            image_bytes_data = await asyncio.to_thread(fetch_thumbnail)
            image_bytes = BytesIO(image_bytes_data)
            toga_image = toga.Image(src=image_bytes.read())
            
            # Set the image (Toga will stretch it here by default)
            self.image_view.image = toga_image
            
            # --- CRITICAL FIX: Re-apply Native iOS Styling AFTER setting the image ---
            import sys
            if sys.platform == 'ios':
                try:
                    native_img_view = self.image_view._impl.native
                    native_img_view.contentMode = 2 # UIViewContentModeScaleAspectFill
                    native_img_view.clipsToBounds = True
                    native_img_view.layer.cornerRadius = 16.0
                except Exception as e:
                    print(f"Could not re-apply iOS native image styling: {e}")
            # -------------------------------------------------------------------------
            
        except Exception as e:
            print(f"Error loading image: {e}")
        finally:
            self.url_input.enabled = True
            self.paste_button.enabled = True
            self.filename_input.enabled = False
            self.filename_input.value = filename
            
            # Update button UI if a batch was loaded
            self.download_button.enabled = True
            if hasattr(self, 'batch_urls') and len(self.batch_urls) > 1:
                self.download_button.text = f"Download {len(self.batch_urls)} Items"
            else:
                self.download_button.text = "Download"

            self.image_view.style.visibility = 'visible'
            self.filename_input_label.style.visibility = 'visible'
            self.filename_input.style.visibility = 'visible'
            self.download_button.style.visibility = 'visible'
            self.progress.stop()
            
    async def show_downloading_layout(self):
        print("show_downloading_layout")

        # update download button
        self.download_button.text = "Downloading…"

        # disable buttons
        self.paste_button.enabled = False
        self.download_button.enabled = False

        # disable textinputs
        self.url_input.enabled = False
        self.filename_input.enabled = False
        
        # --- CRITICAL FIX: Re-apply Native iOS Styling AFTER setting the image ---
        import sys
        if sys.platform == 'ios':
            try:
                native_img_view = self.image_view._impl.native
                native_img_view.contentMode = 2 # UIViewContentModeScaleAspectFill
                native_img_view.clipsToBounds = True
                native_img_view.layer.cornerRadius = 16.0
            except Exception as e:
                print(f"Could not re-apply iOS native image styling: {e}")
        # -------------------------------------------------------------------------

    def input_change(self, widget):
        if self.url_input.value == "":
            print("textinput cleared")

            # reset progress bar
            self.progress.value = 0
            self.progress.max = None

            # hide preview widgets
            self.image_view.style.visibility = 'hidden'
            self.filename_input_label.style.visibility = 'hidden'
            self.filename_input.style.visibility = 'hidden'
            self.download_button.style.visibility = 'hidden'
        else:
            # VSCO specific regex
            url_pattern = re.compile(r"^(?:https?://)?(?:www\.)?(?:vsco\.co|vs\.co)(?:/.*)?$", re.IGNORECASE)
            
            # Auto-trigger if the typed/pasted text is a valid VSCO link
            if url_pattern.match(self.url_input.value):
                asyncio.create_task(self.load_input(widget))
            
    def get_clipboard_text(self):
        """Cross-platform helper to grab text from the system clipboard."""
        import sys
        if sys.platform == 'ios':
            try:
                from rubicon.objc import ObjCClass
                UIPasteboard = ObjCClass("UIPasteboard")
                pb = UIPasteboard.generalPasteboard
                # pb.string returns an NSString, so we cast it to a standard Python str
                return str(pb.string) if pb.string else ""
            except Exception as e:
                print(f"Error reading iOS clipboard: {e}")
                return ""
        else:
            # Fallback for Desktop environments
            try:
                import pyperclip
                return pyperclip.paste()
            except ImportError:
                print("Install 'pyperclip' (pip install pyperclip) to test clipboard on desktop.")
                return ""

    async def paste_and_load(self, widget):
        """Action for the lightning button."""
        clip_text = self.get_clipboard_text()
        
        if clip_text:
            # 1. Inject the text into the input box.
            # If the text is invalid, Toga's validator will immediately raise a ValueError.
            # We MUST catch this error so the function doesn't crash!
            try:
                self.url_input.value = clip_text
            except ValueError:
                pass  # Ignore the crash so we can show our dialog below!
            
            # 2. Check if the pasted text is valid
            url_pattern = re.compile(r"^(?:https?://)?(?:www\.)?(?:vsco\.co|vs\.co)(?:/.*)?$", re.IGNORECASE)
            
            if not url_pattern.match(clip_text):
                # If it's invalid, alert the user with a dialog
                await self.main_window.dialog(
                    toga.InfoDialog(
                        "Invalid Link",
                        "The copied text is not a valid VSCO link (vsco.co or vs.co)."
                    )
                )
            # (If it IS valid, the input_change listener has already detected it and started loading!)
                
        else:
            # Alert the user if the clipboard is completely empty
            await self.main_window.dialog(
                toga.InfoDialog(
                    "Clipboard Empty",
                    "There is no text copied to your clipboard to paste."
                )
            )

    async def load_input(self, widget):
        if not self.url_input.enabled:
            return

        self.app.main_window.content = self.app.main_window.content
        url_pattern = re.compile(r"^(?:https?://)?(?:www\.)?(?:vsco\.co|vs\.co)(?:/.*)?$", re.IGNORECASE)

        print(f"\n[LOG] ====== NEW LOAD INITIATED ======")
        print(f"[LOG] Raw Input: {self.url_input.value}")

        if self.url_input.value and url_pattern.match(self.url_input.value):
            self.show_loading_layout()

            try:
                target_url = self.url_input.value
                if not target_url.startswith("http"):
                    target_url = "https://" + target_url

                print(f"[LOG] Formatted target URL: {target_url}")

                # --- NEW: SHORTLINK RESOLUTION ---
                if "vs.co" in target_url:
                    print("[LOG] Shortlink detected (vs.co). Resolving via WebView...")
                    self.main_webview.url = target_url
                    await asyncio.sleep(4.0) # Give WebKit time to follow redirects
                    
                    # Grab the final resolved URL from the WebView
                    resolved_url = await self.main_webview.evaluate_javascript("window.location.href")
                    if resolved_url and "vsco.co" in resolved_url:
                        target_url = resolved_url.split('?')[0]
                        print(f"[LOG] Shortlink resolved to: {target_url}")
                    else:
                        print(f"[LOG] Warning: Could not cleanly resolve shortlink. WebView is at: {resolved_url}")

                # Determine if this is a single post or a profile/collection
                is_profile = "/media/" not in target_url and "/video/" not in target_url

                print(f"[LOG] Mode selection -> is_profile: {is_profile}")

                if is_profile:
                    print("[LOG] --- EXECUTING BATCH PROFILE LOGIC ---")
                    if not target_url.endswith("/gallery") and "/collection" not in target_url:
                        target_url = target_url.rstrip("/") + "/gallery"
                        print(f"[LOG] Adjusted profile URL to: {target_url}")
                    
                    self.main_webview.url = target_url

                    print("[LOG] Waiting 3.9 seconds for WebKit to render the profile DOM...")
                    await asyncio.sleep(3.9)
                    raw_html = await self.main_webview.evaluate_javascript("document.documentElement.innerHTML")
                    
                    # Force raw_html to be a string so Python never throws a NoneType crash
                    raw_html = raw_html or ""
                    
                    if "just a moment" in raw_html.lower() or "cloudflare" in raw_html.lower():
                        print("[LOG] Cloudflare challenge detected! Waiting 1.8 extra seconds...")
                        await asyncio.sleep(1.8)
                        raw_html = await self.main_webview.evaluate_javascript("document.documentElement.innerHTML")
                        raw_html = raw_html or ""

                    self.batch_urls = []
                    
                    # --- PHASE 1: Direct HTML Extraction ---
                    print("[LOG] Phase 1: Extracting pre-rendered items from the DOM...")
                    
                    # 1. Grab all im.vsco.co image links directly from the rendered HTML tags
                    img_matches = re.findall(r'(?:https?://)?im\.vsco\.co/[^"\'\s\\]+', raw_html)
                    for dlu in img_matches:
                        if not dlu.startswith("http"):
                            dlu = "https://" + dlu
                        dlu = dlu.replace('\\/', '/').replace('\\u002F', '/').split('?')[0]
                        if dlu not in self.batch_urls:
                            self.batch_urls.append(dlu)
                            
                    # 2. Grab all Mux video IDs from the DOM
                    mux_matches = re.findall(r'stream\.mux\.com(?:/|\\/|\\u002F)([a-zA-Z0-9_-]+)', raw_html)
                    for playback_id in mux_matches:
                        dlu = f"https://stream.mux.com/{playback_id}/high.mp4"
                        if dlu not in self.batch_urls:
                            self.batch_urls.append(dlu)

                    print(f"[LOG] Phase 1 Complete. Found {len(self.batch_urls)} initial items.")
                    
                    # --- Sync the UI button with the initial Phase 1 count ---
                    self.download_button.text = f"Loading {len(self.batch_urls)} Items..."

                    # --- PHASE 2: Offline API Extraction (The Kotlin Way) ---
                    print("[LOG] Phase 2: Extracting API credentials directly from DOM...")
                    
                    intercepted_json = None
                    
                    # 1. Extract the Site ID (User ID)
                    site_id_match = re.search(r'vsco://user/(\d+)', raw_html)
                    if not site_id_match:
                        site_id_match = re.search(r'"site_?id"\s*:\s*"?(\d+)"?', raw_html, re.IGNORECASE)
                        
                    site_id = site_id_match.group(1) if site_id_match else None
                    print(f"[LOG] Extracted Site ID: {site_id}")
                    
                    # 2. Extract the Bearer Token
                    token = None
                    
                    # Pattern A: Literally "Bearer <token>"
                    t_match = re.search(r'(Bearer [a-zA-Z0-9\-\_\.]+)', raw_html)
                    if t_match:
                        token = t_match.group(1)
                    else:
                        # Pattern B: Next.js/Redux JSON {"tkn": "hex..."} or {"token": "hex..."}
                        t_match = re.search(r'"t(?:oke)?n"\s*:\s*"([a-fA-F0-9]{30,50})"', raw_html)
                        if t_match:
                            token = f"Bearer {t_match.group(1)}"
                            
                    if token:
                        print(f"[LOG] Extracted Bearer Token: {token[:15]}...")
                    else:
                        print("[LOG] Warning: Could not find Bearer token in HTML. Falling back to Master Visitor Token.")
                        # Fallback: The long-standing VSCO public visitor token
                        token = "Bearer 7356455548d0a1d886db010883388d08be84d0c9"
                        
                    # 3. Construct the API Payload manually
                    if site_id and token:
                        base_url = f"https://vsco.co/api/3.0/medias/profile?site_id={site_id}"
                        intercepted_json = json.dumps({
                            "url": base_url,
                            "headers": {
                                "Authorization": token,
                                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15"
                            }
                        })
                        print("[LOG] API Payload successfully constructed offline!")
                    
                    if intercepted_json:
                        print("[LOG] Moving to fetch_profile_media recursive loop...")
                        await self.fetch_profile_media(intercepted_json)
                    else:
                        print("[LOG] WARNING: Failed to extract credentials offline. Proceeding with Phase 1 items only.")

                    if not self.batch_urls:
                        print("[LOG] FATAL: No media found on this profile.")
                        raise Exception("No media found on this profile.")

                    print(f"[LOG] Profile batch complete. Total items queued: {len(self.batch_urls)}")

                    title = target_url.split("vsco.co/")[1].split("/")[0]
                    filename = sanitize_filename(title)
                    thumbnail_url = self.batch_urls[0]
                    
                    await self.show_preview_layout(filename, thumbnail_url)

                else:
                    print("[LOG] --- EXECUTING SINGLE MEDIA LOGIC ---")
                    self.batch_urls = []
                    self.main_webview.url = target_url
                    
                    print("[LOG] Waiting 1.6 seconds for single media page to load...")
                    await asyncio.sleep(1.6)

                    html = await self.main_webview.evaluate_javascript("document.documentElement.innerHTML")
                    if html and ("just a moment" in html.lower() or "cloudflare" in html.lower()):
                        print("[LOG] Cloudflare challenge detected, waiting 1.3 more seconds...")
                        await asyncio.sleep(1.3)
                        html = await self.main_webview.evaluate_javascript("document.documentElement.innerHTML")

                    if not html:
                        print("[LOG] FATAL: WebView failed to return HTML.")
                        raise Exception("WebView failed to load the HTML.")

                    print("[LOG] Parsing HTML for media tags...")
                    info = self.parse_vsco_html(html)
                    self.current_download_url = info["download_url"]
                    self.current_ext = info["ext"]
                    
                    print(f"[LOG] Single media extracted successfully. Type: {self.current_ext}")
                    await self.show_preview_layout(sanitize_filename(info["title"][0:23]), info["thumbnail"])
                
            except Exception as e:
                print(f"[LOG] EXTRACTION ERROR: {e}")
                self.url_input.enabled = True
                self.paste_button.enabled = True
                self.progress.stop()
                self.progress.style.visibility = 'hidden'
                await self.main_window.dialog(toga.InfoDialog("Extraction Failed", str(e)))
        else:
            print("[LOG] Validation failed: Invalid URL pasted.")
            await self.main_window.dialog(toga.InfoDialog("Error: Invalid URL", "Please paste a valid VSCO link."))
            
    async def fetch_profile_media(self, intercepted_json_str):
        print("\n[LOG] --- BEGINNING RECURSIVE API FETCH ---")
        
        # Log exactly what we are trying to parse so we can debug if it fails again
        preview = str(intercepted_json_str)[:150]
        print(f"[LOG] Intercepted payload preview: {preview}")
        
        import urllib.parse
        import json
        import re
        
        # --- SAFETY FIX 2: Graceful Fallback if JSON decode fails ---
        try:
            api_info = json.loads(intercepted_json_str)
            base_url = api_info.get('url', '')
            headers = api_info.get('headers', {})
        except Exception as e:
            print(f"[LOG] JSON Decode Error: {e}. Attempting Regex Fallback...")
            
            # Bypass JSON entirely and manually scrape the raw string!
            url_match = re.search(r'"url"\s*:\s*"([^"]+)"', str(intercepted_json_str))
            base_url = url_match.group(1) if url_match else ""
            
            auth_match = re.search(r'"[Aa]uthorization"\s*:\s*"([^"]+)"', str(intercepted_json_str))
            headers = {"Authorization": auth_match.group(1)} if auth_match else {}
            
        if not base_url:
            print("[LOG] FATAL: Could not parse base URL from intercepted payload.")
            return # Safely exit the recursion and just rely on the Phase 1 HTML items!
            
        print(f"[LOG] Base API URL extracted: {base_url.split('?')[0]}")

        if "limit=" in base_url:
            base_url = base_url.split("limit=")[0] + "limit=14&cursor="
        else:
            base_url += "&limit=14&cursor="

        visited_cursors = set()
        cursor = ""
        
        while len(visited_cursors) < 200:
            current_url = base_url + urllib.parse.quote(cursor)
            print(f"[LOG] Fetching API page {len(visited_cursors) + 1}...")
            
            # Upgraded JS: Catches HTTP status codes and detailed fetch errors!
            js_fetch = f"""
            window.vscoFetchResult = "PENDING";
            fetch("{current_url}", {{headers: {json.dumps(headers)}}})
                .then(async res => {{
                    const text = await res.text();
                    // If the server rejects us, append the status code to the front!
                    return res.ok ? text : "HTTP_ERROR_" + res.status + ": " + text;
                }})
                .then(text => window.vscoFetchResult = text)
                .catch(err => window.vscoFetchResult = "FETCH_ERROR: " + err.message);
            
            "STARTED";
            """
            await self.main_webview.evaluate_javascript(js_fetch)
            
            response_text = "PENDING"
            while response_text == "PENDING":
                raw_response = await self.main_webview.evaluate_javascript("window.vscoFetchResult")
                
                if raw_response is None:
                    pass
                elif hasattr(raw_response, 'UTF8String'):
                    try:
                        response_text = raw_response.UTF8String().decode('utf-8')
                    except Exception:
                        response_text = str(raw_response)
                else:
                    response_text = str(raw_response)
                    
                await asyncio.sleep(0.1)
                
            if not response_text or response_text.startswith("FETCH_ERROR"):
                print(f"[LOG] API fetch failed entirely: {response_text}")
                break
                
            if response_text.startswith("HTTP_ERROR"):
                print(f"[LOG] FATAL: Server rejected API call. Response: {response_text[:150]}")
                break
                
            items_added = 0
            cursor_val = None

            # --- THE FINAL FIX: Clean JSON Dictionary Parsing ---
            try:
                # We bypassed the browser and hit the API directly, so it's clean JSON!
                api_data = json.loads(response_text)
                
                # 1. Safely extract media items from the array
                for item in api_data.get("media", []):
                    dlu = None
                    
                    # Check for Videos
                    if "video" in item and item["video"]:
                        if "mux_playback_id" in item["video"]:
                            dlu = f"https://stream.mux.com/{item['video']['mux_playback_id']}/high.mp4"
                        elif "video_url" in item["video"]:
                            dlu = item["video"]["video_url"]
                            
                    # Check for Images
                    elif "image" in item and item["image"]:
                        if "responsive_url" in item["image"]:
                            dlu = item["image"]["responsive_url"]
                        elif "adaptive_base" in item["image"]: # <--- This catches what we saw in your log!
                            dlu = "im.vsco.co" + item["image"]["adaptive_base"]
                            
                    # Clean and queue the URL
                    if dlu:
                        if not dlu.startswith("http"):
                            dlu = "https://" + dlu
                        dlu = dlu.replace('\\/', '/').replace('\\u002F', '/').split('?')[0]
                        
                        if dlu not in self.batch_urls:
                            self.batch_urls.append(dlu)
                            items_added += 1
                
                # 2. Extract the Next Cursor directly from the dictionary
                cursor_val = api_data.get("next_cursor") or api_data.get("cursor")
                
            except Exception as e:
                print(f"[LOG] Direct JSON parse failed, falling back to Regex... {e}")
                
                # Regex Fallback just in case VSCO scrambles the JSON structure
                img_matches = re.findall(r'"(?:responsive_?[uU]rl|adaptive_base)"\s*:\s*"([^"]+)"', response_text)
                for dlu in img_matches:
                    if dlu.startswith("/i/"): dlu = "im.vsco.co" + dlu
                    if not dlu.startswith("http"): dlu = "https://" + dlu
                    dlu = dlu.replace('\\/', '/').replace('\\u002F', '/').split('?')[0]
                    if dlu not in self.batch_urls:
                        self.batch_urls.append(dlu)
                        items_added += 1
                        
                cursor_match = re.search(r'"next_cursor"\s*:\s*"([^"]+)"', response_text)
                if cursor_match:
                    cursor_val = cursor_match.group(1)

            print(f"[LOG] Added {items_added} items from API page {len(visited_cursors) + 1}. Total queue: {len(self.batch_urls)}")
            
            # --- NEW: Sync the UI button with the ongoing Phase 2 count ---
            self.download_button.text = f"Loading {len(self.batch_urls)} Items..."

            # Loop back if we found a valid cursor
            if cursor_val and str(cursor_val) != "null" and cursor_val not in visited_cursors:
                visited_cursors.add(cursor_val)
                cursor = cursor_val
                await asyncio.sleep(0.3) # Give the server a quick breather
                continue
            
            print("[LOG] No next_cursor found, or items exhausted. Ending API loop.")
            break
            
    def parse_vsco_html(self, html):
        download_url = ""
        thumbnail_url = ""
        ext = "jpg"
        
        # 1. MP4 (Direct img.vsco.co search)
        if "https://img.vsco.co/" in html:
            match = re.search(r'(https://img\.vsco\.co/[^"]+)', html)
            if match:
                download_url = match.group(1)
                ext = "mp4"

        # 2. Mux Video Stream search
        elif "stream.mux.com" in html:
            match = re.search(r'(stream\.mux\.com[^"]+)', html)
            if match:
                download_url = "https://" + match.group(1).replace("\\u002F", "/")
                ext = "mp4"
        
        # 3. Standard Image search
        elif "im.vsco.co/" in html:
            match = re.search(r'(https://im\.vsco\.co/[^"]+)', html)
            if match:
                download_url = match.group(1).split('?')[0]
        
        # 4. Fallback to OpenGraph image
        if not download_url:
            match = re.search(r'property="og:image" content="([^"]+)"', html)
            if match:
                download_url = match.group(1).split('?')[0]

        # 5. Extract Thumbnail (Aligned 1-to-1 with Kotlin's extractThumbnail)
        if "https://image.mux.com/" in html:
            start = html.find("https://image.mux.com/")
            if start != -1:
                # Substring from the URL start, stopping at the first quote or space
                tu = html[start:].split('"')[0].split("'")[0].split(' ')[0]
                tu = tu.replace('\\', '') # Clean any JSON escaping
                thumbnail_url = tu.split('?')[0]
                
        elif "https://vsco.co/api/1.0/videos/mux/" in html:
            start = html.find("https://vsco.co/api/1.0/videos/mux/")
            if start != -1:
                tu = html[start:].split('"')[0].split("'")[0].split(' ')[0]
                tu = tu.replace('\\', '')
                thumbnail_url = tu.split('?')[0] + "?w=1200"
                
        elif "https://im.vsco.co/" in html:
            # Kotlin uses lastIndexOf for standard images, we use rfind()
            start = html.rfind("https://im.vsco.co/")
            if start != -1:
                tu = html[start:].split('"')[0].split("'")[0].split(' ')[0]
                tu = tu.replace('\\', '')
                thumbnail_url = tu.split('?')[0]
                
        if not thumbnail_url:
            thumbnail_url = download_url

        # 6. Title Generation
        title_match = re.search(r'<title>(.*?)</title>', html)
        title = "vsco_media"
        if title_match:
            raw_title = title_match.group(1)
            parts = raw_title.split("|")
            title = parts[-2].strip() if len(parts) >= 3 else (parts[0].strip() if parts else raw_title.strip())
            title = re.sub(r'[^a-zA-Z0-9_\-]', '', title.replace(' ', '_'))
        
        if not title:
            title = "vsco_download"

        if not download_url:
            raise Exception("Could not find media URLs in the page HTML.")

        return {
            "title": title,
            "ext": ext,
            "thumbnail": thumbnail_url,
            "download_url": download_url
        }
        
        
    async def download_input(self, widget):
        self.app.main_window.content = self.app.main_window.content
        await self.show_downloading_layout()
        
        # Prevent screen sleep during download
        if sys.platform == 'ios':
            try:
                from rubicon.objc import ObjCClass
                UIApplication = ObjCClass("UIApplication")
                UIApplication.sharedApplication.idleTimerDisabled = True
            except Exception as e:
                print(f"Could not disable idle timer: {e}")

        try:
            # --- BATCH DOWNLOAD LOOP ---
            if hasattr(self, 'batch_urls') and len(self.batch_urls) > 0:
                total = len(self.batch_urls)
                self.progress.max = total
                self.progress.value = 0
                self.progress.style.visibility = 'visible'

                for index, url in enumerate(self.batch_urls):
                    self.download_button.text = f"Downloading {index+1} of {total}...\nPlease keep app open."
                    
                    ext = "mp4" if ".mp4" in url or "mux.com" in url else "jpg"
                    filename = f"{self.filename_input.value}_{index+1}"

                    # Empty hook to suppress individual file progress logging
                    def batch_hook(d): pass

                    await dl_vsco_async(url, get_dest_path(), filename, ext, batch_hook)
                    self.progress.value = index + 1
                    
            # --- SINGLE FILE DOWNLOAD ---
            else:
                pb = self.progress
                ph = await create_progress_hook(pb)
                await dl_vsco_async(self.current_download_url, get_dest_path(), self.filename_input.value, self.current_ext, ph)
                self.progress.stop()
                self.progress.max = 100
                self.progress.value = 100

            self.download_button.text = "Finished!"
            self.url_input.enabled = True
            self.paste_button.enabled = True
            self.filename_input.enabled = False
            
            # Allow screen sleep after download finished
            if sys.platform == 'ios':
                try:
                    UIApplication.sharedApplication.idleTimerDisabled = False
                except Exception:
                    pass
            
        except Exception as e:
            print(f"Download failed: {e}")
            self.download_button.text = "Error"
            self.download_button.enabled = True
            self.progress.stop()
            self.progress.style.visibility = 'hidden'
            self.url_input.enabled = True
            self.paste_button.enabled = True
            self.filename_input.enabled = False
            await self.main_window.dialog(toga.InfoDialog("Download Failed", str(e)))


def main():
    return VsLoader()


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
    """Custom Toga validator to check for valid HTTP/HTTPS URLs."""
    if not value:
        return  # Allow empty (matches your current allow_empty=True behavior)
    
    # Standard regex for robust URL validation
    url_pattern = re.compile(r"^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)$")
    
    if not url_pattern.match(value):
        raise ValueError("Please paste a valid URL")


async def extract_vsco_info(vsco_url, resolution):
    """
    Extracts VSCO media directly from HTML using curl_cffi
    to bypass Cloudflare TLS fingerprinting blocks.
    """
    print(f"Starting HTML extraction for: {vsco_url}")
    
    def extract():
        target_url = vsco_url
        
        # The 'impersonate' argument handles all the complex TLS spoofing
        # and header generation automatically!
        res = requests.get(target_url, impersonate="chrome", timeout=15, allow_redirects=True)
        
        target_url = res.url.split('?')[0]
        html = res.text

        # Fallback shortlink resolution
        if "vs.co/" in target_url:
            canonical_match = re.search(r'(https://vsco\.co/[^"\'\s>]+)', html)
            if canonical_match:
                target_url = canonical_match.group(1).split('?')[0]
                # Re-fetch with impersonation
                res = requests.get(target_url, impersonate="chrome", timeout=15)
                html = res.text

        if res.status_code == 403:
            raise Exception("Cloudflare is still blocking the request. Your IP may be temporarily flagged.")

        # --- The rest of your regex extraction logic stays exactly the same ---
        download_url = ""
        thumbnail_url = ""
        ext = "jpg"
        
        video_match = re.search(r'property="og:video" content="([^"]+)"', html)
        if video_match:
            v_url = video_match.group(1).replace("&amp;", "&")
            v_res = requests.get(v_url, impersonate="chrome", timeout=15)
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
    """Downloads the direct media URL."""
    print(f"starting dl_vsco_async for direct URL: {download_url}")
    
    def download():
        os.makedirs(out_path, exist_ok=True)
        dest = os.path.join(out_path, f"{filename}.{ext}")
        
        # set user agent
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }

        # --- IMAGE DOWNLOAD LOGIC ---
        if ext in ["jpg", "jpeg", "png"]:
            print("Downloading image via requests...")
            res = requests.get(download_url, stream=True, timeout=15, headers=headers)
            res.raise_for_status()
            
            total_bytes = int(res.headers.get('content-length', 0))
            downloaded_bytes = 0
            
            with open(dest, 'wb') as f:
                for chunk in res.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded_bytes += len(chunk)
                        if total_bytes:
                            progress_hook({
                                'status': 'downloading',
                                'downloaded_bytes': downloaded_bytes,
                                'total_bytes': total_bytes
                            })
                            
            progress_hook({'status': 'finished'})

        # --- VIDEO DOWNLOAD LOGIC ---
        else:
            print("Downloading video stream manually...")
            progress_hook({'status': 'downloading'})
            
            m3u8_res = requests.get(download_url, headers=headers, timeout=15)
            m3u8_res.raise_for_status()
            
            lines = m3u8_res.text.split('\n')
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
                    ts_res = requests.get(ts_url, headers=headers, timeout=15)
                    ts_res.raise_for_status()
                    outfile.write(ts_res.content)
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

        # show init layout
        self.show_init_layout()

    def show_init_layout(self):
        print("show_init_layout")
        self.main_box = toga.Box(direction=COLUMN)

        # --- NEW: Hidden WebView to bypass Cloudflare ---
        self.hidden_webview = toga.WebView(style=Pack(width=1, height=1))
        self.hidden_webview.style.visibility = 'hidden'
        self.main_box.add(self.hidden_webview)
        # ------------------------------------------------

        # hint
        hint_label = toga.Label(
            "Paste URL:",
            font_family="FiraSans",
            margin=(8, 8, 4, 8),
        )
        self.hint_box = toga.Box(children=[hint_label])

        # url textinput
        self.url_input = toga.TextInput(direction=ROW,
                                        on_confirm=self.load_input,
                                        on_change=self.input_change,
                                        flex=1,
                                        validators=[validate_url],
                                        style=Pack(height=45))
        # paste button
        self.paste_button = toga.Button(
            icon=toga.Icon("resources/bolt_512"),
            on_press=self.paste_and_load,
            margin=(0, 0, 0, 4),
            style=Pack(width=45) # Forces the button to remain comfortably wide
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
        self.image_view = toga.ImageView(image=None, height=320, direction=COLUMN, flex=1)
        self.image_box = toga.Box(children=[self.image_view], direction=COLUMN, margin=8)
        self.preview_box.add(self.image_box)

        # filename box
        self.filename_input_label = toga.Label(
            "Filename:",
            font_family="FiraSans",
            margin=(12, 4, 8, 12)
        )
        self.filename_input = toga.TextInput(margin=(8, 12, 8, 4), direction=ROW, flex=1)
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
        self.main_window = toga.MainWindow(title="MusiLoader")
        self.main_window.content = self.main_box
        self.main_window.show()

    def show_loading_layout(self):
        print("show_loading_layout")

        # disable url textinput
        self.url_input.enabled = False
        self.filename_input.enabled = False

        # hide preview widgets
        self.image_view.style.visibility = 'hidden'
        self.filename_input_label.style.visibility = 'hidden'
        self.filename_input.style.visibility = 'hidden'
        self.download_button.style.visibility = 'hidden'

        # update download button
        self.download_button.text = "Download"
        self.download_button.enabled = True

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

            # set user agent
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            response = await asyncio.to_thread(requests.get, thumbnail_url, headers=headers)
            response.raise_for_status()

            image_bytes = BytesIO(response.content)
            toga_image = toga.Image(src=image_bytes.read())
            self.image_view.image = toga_image
        except requests.exceptions.RequestException as e:
            print(f"Error loading image: {e}")
        finally:
            self.url_input.enabled = True
            self.paste_button.enabled = True
            self.filename_input.enabled = True
            self.filename_input.value = filename
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
            # Regex pattern to ensure the string is actually a safe, valid URL
            url_pattern = re.compile(r"^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)$")
            
            # Auto-trigger if the typed/pasted text is fully valid
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
            # Updating the value automatically fires the input_change event!
            self.url_input.value = clip_text

    async def load_input(self, widget):
        # Guard clause: Prevent double-triggering
        if not self.url_input.enabled:
            return

        # hide keyboard
        self.app.main_window.content = self.app.main_window.content

        # URL validation regex pattern
        url_pattern = re.compile(r"^https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)$")

        # validate input with regex
        if self.url_input.value and url_pattern.match(self.url_input.value):
            # show loading ui
            self.show_loading_layout()

            try:
                target_url = self.url_input.value

                # 1. Load URL natively in iOS WebKit to bypass Cloudflare
                self.hidden_webview.url = target_url

                # 2. Give the page a few seconds to negotiate TLS and load the DOM
                await asyncio.sleep(4.0)

                # 3. Extract HTML via JavaScript
                html = await self.hidden_webview.evaluate_javascript("document.documentElement.innerHTML")
                
                # Check if Cloudflare challenged us
                if html and ("just a moment" in html.lower() or "cloudflare" in html.lower()):
                    print("Cloudflare challenge detected. Waiting 3 more seconds...")
                    await asyncio.sleep(3.0)
                    html = await self.hidden_webview.evaluate_javascript("document.documentElement.innerHTML")

                if not html:
                    raise Exception("WebView failed to load the HTML.")

                # 4. Parse the DOM (Sync, because Regex is instant)
                info = self.parse_vsco_html(html)

                title = info["title"]
                ext = info["ext"]
                thumbnail_url = info["thumbnail"]
                filename = sanitize_filename(title[0:23])

                # SAVE THESE TO THE CLASS INSTANCE
                self.current_download_url = info["download_url"]
                self.current_ext = ext

                await self.show_preview_layout(filename, thumbnail_url)
                
            except Exception as e:
                print(f"Extraction Error: {e}")
                
                self.url_input.enabled = True
                self.paste_button.enabled = True
                self.progress.stop()
                self.progress.style.visibility = 'hidden'
                
                await self.main_window.dialog(
                    toga.InfoDialog(
                        "Extraction Failed",
                        str(e)
                    )
                )
        else:
            await self.main_window.dialog(
                toga.InfoDialog(
                    "Error: Invalid URL",
                    "Please paste a valid URL"
                )
            )
            
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
                
        # 5. Extract Thumbnail
        if ext == "mp4":
            poster_match = re.search(r'property="og:image" content="([^"]+)"', html)
            if poster_match:
                thumbnail_url = poster_match.group(1).split('?')[0]
        else:
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
        # hide keyboard
        self.app.main_window.content = self.app.main_window.content

        # update ui (fallback to show_loading_layout since show_downloading_layout is missing)
        self.show_loading_layout()

        pb = self.progress
        ph = await create_progress_hook(pb)

        dl_task = asyncio.create_task(
            dl_vsco_async(self.current_download_url,
                           get_dest_path(),
                           f"{self.filename_input.value}",
                           self.current_ext,
                           ph))
        
        try:
            await dl_task
            print("finished download!")
            
            # stop progress bar
            self.progress.stop()
            self.progress.max = 100
            self.progress.value = 100

            # show finished layout
            self.download_button.text = "Finished!"
            self.url_input.enabled = True
            self.paste_button.enabled = True
            print("finished showing finished layout!")
            
        except Exception as e:
            print(f"Download failed: {e}")
            self.download_button.text = "Error"
            self.progress.stop()
            self.progress.style.visibility = 'hidden'
            self.url_input.enabled = True
            self.paste_button.enabled = True
            await self.main_window.dialog(
                toga.InfoDialog("Download Failed", str(e))
            )


def main():
    return VsLoader()


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
import gallery_dl
import re
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
    Extracts metadata from a VSCO URL using gallery-dl's DataJob.
    Includes shortlink resolution and debug logging.
    """
    print(f"starting extract_vsco_info for: {vsco_url}")
    
    def extract():
        # 1. Resolve shortlinks (vs.co -> vsco.co)
        target_url = vsco_url
        if "vs.co/" in target_url:
            print("Shortlink detected. Resolving...")
            try:
                # Follow the redirect to get the actual vsco.co canonical URL
                res = requests.head(target_url, allow_redirects=True, timeout=10)
                target_url = res.url
                print(f"Resolved to: {target_url}")
            except Exception as e:
                print(f"Failed to resolve shortlink: {e}")

        # 2. Setup gallery-dl config with DEBUG logging
        gallery_dl.config.clear()
        gallery_dl.config.set((), "log", {"level": "debug"})
        
        # 3. Capture BOTH stdout (JSON data) and stderr (Debug Logs)
        f_out = io.StringIO()
        f_err = io.StringIO()
        
        with contextlib.redirect_stdout(f_out), contextlib.redirect_stderr(f_err):
            try:
                j = gallery_dl.job.DataJob(target_url)
                j.run()
            except Exception as e:
                # If gallery-dl throws a hard exception, catch it
                raise Exception(f"Job failed: {str(e)}\nLogs: {f_err.getvalue()}")
            
        output = f_out.getvalue().strip()
        debug_logs = f_err.getvalue().strip()
        
        # 4. Better error surfacing
        if not output:
            print(f"--- GALLERY-DL DEBUG LOGS ---\n{debug_logs}\n-----------------------------")
            raise Exception("gallery-dl returned no data. Check the debug logs printed in the console.")
            
        # Parse the JSON
        lines = output.split('\n')
        data = json.loads(lines[0])
        
        metadata = data[2] if len(data) > 2 else {}
        
        return {
            "title": metadata.get("shortcode", metadata.get("id", "VSCO_Media")),
            "ext": metadata.get("extension", "jpg"),
            "thumbnail": metadata.get("url", "")
        }

    return await asyncio.to_thread(extract)


async def dl_video_async(vsco_url, out_path, filename, resolution, progress_hook):
    """
    Downloads the VSCO media via gallery-dl's DownloadJob.
    """
    print("starting dl_video_async")
    
    def download():
        # Reset config for a clean download state
        gallery_dl.config.clear()
        gallery_dl.config.set((), "log", {"level": "error"})
        
        # Set base destination folder based on your OS get_dest_path()
        gallery_dl.config.set(("extractor",), "base-directory", out_path)
        
        # Prevent gallery-dl from creating default nested folders (e.g., /vsco/username/)
        gallery_dl.config.set(("extractor",), "directory", [])
        
        # Differentiate between a single item and a gallery
        is_gallery = 'gallery' in vsco_url or '/user/' in vsco_url
        
        if is_gallery:
            # gallery-dl's equivalent of %(autonumber)s is {num}
            gallery_dl.config.set(("extractor",), "filename", f"{filename}_{{num}}.{{extension}}")
        else:
            gallery_dl.config.set(("extractor",), "filename", f"{filename}.{{extension}}")

        # Trigger your UI's indeterminate progress state since gallery-dl
        # doesn't natively pipe byte-level download updates to a Python hook
        progress_hook({'status': 'downloading'})

        # Execute the download
        j = gallery_dl.job.DownloadJob(vsco_url)
        j.run()

        # Alert the UI it's done
        progress_hook({'status': 'finished'})

    # Push the blocking download to a background thread
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

    # button.style.margin = (5, 10, 15, 20)  ->  (top, right, bottom, left)
    def show_init_layout(self):
        print("show_init_layout")
        self.main_box = toga.Box(direction=COLUMN)

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

        # convert webp thumbnail urls to jpg
        if thumbnail_url.endswith(".webp"):
            thumbnail_url = thumbnail_url.replace("vi_webp", "vi")
            thumbnail_url = thumbnail_url.replace(".webp", ".jpg")

        try:
            print(f"loading thumbnail_url: {thumbnail_url}")

            # Push the blocking network request to a background thread
            response = await asyncio.to_thread(requests.get, thumbnail_url)
            response.raise_for_status()  # Raise an exception for bad status codes
            image_bytes = BytesIO(response.content)
            toga_image = toga.Image(src=image_bytes.read())
            self.image_view.image = toga_image
        except requests.exceptions.RequestException as e:
            # Handle potential errors during image download
            print(f"Error loading image: {e}")
            # error_label = toga.Label(f"Error loading image: {e}")
            # self.main_window.content = toga.Box(children=[error_label])
        finally:
            # enable url textinput
            self.url_input.enabled = True

            # enable paste button
            self.paste_button.enabled = True

            # enable textinputs
            self.filename_input.enabled = True
            self.url_input.enabled = True

            # set current filename
            self.filename_input.value = filename

            # show preview widgets
            self.image_view.style.visibility = 'visible'
            self.filename_input_label.style.visibility = 'visible'
            self.filename_input.style.visibility = 'visible'
            self.download_button.style.visibility = 'visible'

            # stop indeterminate progress
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
                # load media info asynchronously
                load_task = asyncio.create_task(
                    extract_vsco_info(f"{self.url_input.value}", "2160"))
                info = await load_task

                title = info["title"]
                ext = info["ext"]
                thumbnail_url = info["thumbnail"]
                filename = sanitize_filename(title[0:23])

                await self.show_preview_layout(filename, thumbnail_url)
                
            except Exception as e:
                # 1. Log the previously swallowed exception!
                print(f"Extraction Error: {e}")
                
                # 2. Reset the UI so it doesn't get stuck
                self.url_input.enabled = True
                self.paste_button.enabled = True
                self.progress.stop()
                self.progress.style.visibility = 'hidden'
                
                # 3. Alert the user
                await self.main_window.dialog(
                    toga.InfoDialog(
                        "Extraction Failed",
                        "Could not load preview"
                    )
                )
        else:
            await self.main_window.dialog(
                toga.InfoDialog(
                    "Error: Invalid URL",
                    "Please paste a valid URL"
                )
            )

    async def download_input(self, widget):
        # hide keyboard
        self.app.main_window.content = self.app.main_window.content

        # update ui
        await self.show_downloading_layout()

        pb = self.progress
        ph = await create_progress_hook(pb)

        dl_task = asyncio.create_task(
            dl_video_async(f"{self.url_input.value}",
                           get_dest_path(),
                           f"{self.filename_input.value}",
                           "2160",
                           ph))
        await dl_task
        print(f"finished download!")

        # stop progress bar
        self.progress.stop()
        self.progress.max = 100
        self.progress.value = 100

        # show finished layout
        self.download_button.text = "Finished!"
        self.url_input.enabled = True
        self.paste_button.enabled = True
        print("finished showing finished layout!")


def main():
    return VsLoader()


"""
Video Downloader for iOS
"""

import toga
import asyncio
import queue
from asyncio import TaskGroup
import yt_dlp
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
        return "C:\\Users\\maxwe\\Videos\\SaveFrom\\v8\\"
    elif sys.platform == 'android':
        print("Running on Android.")
        return "/storage/emulated/0/Documents/"
    elif sys.platform == 'darwin':
        print("Running on macOS.")
        return str(Path.home() / "Downloads") + "/"
    else:
        print(f"Running on a different platform: {sys.platform}\nReturning default path_out (windows)")
        return "C:\\Users\\maxwe\\StudioProjects\\savefrom-video-downloader\\"


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


# 'outtmpl': out + '%(title).25s.%(ext)s',
# example formats
# 'format': "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
# 'format': "bestvideo[height<=" + resolution + "], bestaudio",
# 'format': "bestvideo[height<=" + resolution + "]+bestaudio/bestvideo[height<=" + resolution + "]/best[height<=" + resolution + "]",
async def dl_video_async(video_url, out, filename, resolution, progress_hook):
    # find ffmpeg on mobile
    ff_dir_path = ''
    if sys.platform == 'ios':
        file___path = os.path.realpath(__file__)
        file___dir_path = file___path[:file___path.rfine('/')]
        ff_dir_path = os.path.join(file___dir_path, 'ffmpeg', 'bin')
    elif sys.platform == 'android':
        # TODO find ffmpeg on android
        print(f'TODO find ffmpeg location on android')
    print(f'ff_dir_path: {ff_dir_path}')

    # set youtubedl options
    ydl_opts = {
        'format': "bestvideo[height<=" + resolution + "]+bestaudio/bestvideo[height<=" + resolution + "]/best[height<=" + resolution + "]",
        'outtmpl': out + filename + '.%(ext)s',
        'restrictfilenames': True,
        "cachedir": False,
        "ignoreerrors": True,
        'progress_hooks': [progress_hook],
        'ffmpeg_location': ff_dir_path,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # Use asyncio.to_thread to run the blocking download in a separate thread
        await asyncio.to_thread(ydl.download, video_url)
        # return info_dict['format_id']


async def extract_video_info(video_url, resolution):
    # prevent overwrite with random id
    ydl_opts = {
        'format': "bestvideo[height<=" + resolution + "]+bestaudio/bestvideo[height<=" + resolution + "]/best[height<=" + resolution + "]",
        'restrictfilenames': True,
        "cachedir": False,
        "ignoreerrors": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = await asyncio.to_thread(ydl.extract_info, video_url, False)
        video_info = f"{info_dict['title']}|||{info_dict['ext']}|||{info_dict['thumbnail']}"
        print(f"video_info={video_info}")
        return video_info


async def create_progress_hook(progress_bar):
    progress_bar.style.visibility = 'visible'
    # progress_bar.max = 100
    progress_bar.start()

    def progress_hook(d):
        if d['status'] == 'downloading':
            if d.get('total_bytes') and d.get('downloaded_bytes'):
                print("has total_bytes and downloaded_bytes")
                # calculate progress
                percent_float = (d['downloaded_bytes'] / d['total_bytes']) * 100
                percent_int = int(percent_float)
                # update progress
                # progress_bar.value = percent_int
                print(f"Download Progress: {percent_int}%")
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
                                        validators=[StartsWith("https://", error_message="Please paste a valid URL", allow_empty=True),
                                                    MinLength(15, error_message="Please paste a valid URL", allow_empty=True),
        ])
        self.load_button = toga.Button(
            "Load",
            direction=ROW,
            on_press=self.load_input,
            margin=(0, 0, 0, 4),
        )
        self.load_button.style.visibility = 'visible'
        self.url_box = toga.Box(margin=(0, 8))
        self.url_box.add(self.url_input)
        self.url_box.add(self.load_button)

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
        self.main_window = toga.MainWindow(title="VsLoader")
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

        # update load button
        self.load_button.text = "Loading…"
        self.load_button.enabled = False

        # show indeterminate progressbar
        self.progress.max = None
        self.progress.style.visibility = 'visible'
        self.progress.start()

    def show_preview_layout(self, filename, thumbnail_url):
        print("show_preview_layout")

        # convert webp thumbnail urls to jpg
        if thumbnail_url.endswith(".webp"):
            thumbnail_url = thumbnail_url.replace("vi_webp", "vi")
            thumbnail_url = thumbnail_url.replace(".webp", ".jpg")

        try:
            print(f"loading thumbnail_url: {thumbnail_url}")

            # load thumbnail into imageviewL
            response = requests.get(thumbnail_url)
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

            # reset loading widgets
            self.load_button.text = "Load"
            self.load_button.enabled = True

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
        self.load_button.enabled = False
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

    async def load_input(self, widget):
        # hide keyboard
        self.app.main_window.content = self.app.main_window.content

        # validate input
        if "https://" in self.url_input.value and self.url_input.value.count("/") >= 3:
            # show loading ui
            self.show_loading_layout()

            # load video info asynchronously
            load_task = asyncio.create_task(
                extract_video_info(f"{self.url_input.value}", "2160"))
            info = await load_task

            # format file info
            filename_id = f"{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}{random.randint(0, 9)}_"
            index_div1 = info.index("|||")
            index_div2 = info.rindex("|||")
            title = info[:index_div1]
            filename = filename_id + sanitize_filename(title[0:23])
            ext = info[index_div1 + 3:index_div2]
            thumbnail_url = info[index_div2 + 3:]
            print(f"loaded video info:\ntitle={title}\nfilename={filename}\next={ext}\nthumbnail_url={thumbnail_url}")

            self.show_preview_layout(filename, thumbnail_url)
        else:
            self.main_window.dialog(
                toga.InfoDialog(
                    "Error: Invalid URL",
                    "Please paste a video URL"
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
        self.load_button.enabled = True
        print("finished showing finished layout!")


async def main():
    return VsLoader()

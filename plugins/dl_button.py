import logging
logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
import asyncio
import aiohttp # Removed - not needed with yt-dlp for playlist handling
import json
import math
import os
import shutil
import time
from datetime import datetime
from plugins.config import Config
from plugins.script import Translation
from plugins.thumbnail import *
from plugins.database.database import db
logging.getLogger("pyrogram").setLevel(logging.WARNING)
from plugins.functions.display_progress import progress_for_pyrogram, humanbytes, TimeFormatter # TimeFormatter not used, removing
from hachoir.metadata import extractMetadata # Not used, removing
from hachoir.parser import createParser # Not used, removing
from PIL import Image # Not used directly in this function, might be used in thumbnail, keeping for now
from pyrogram import enums


async def ddl_call_back(bot, update):
    logger.info(update)
    cb_data = update.data
    # youtube_dl extractors -  now using yt-dlp for direct links and playlists
    tg_send_type, youtube_dl_format, youtube_dl_ext = cb_data.split("=") # Assuming this still defines format and type
    thumb_image_path = Config.DOWNLOAD_LOCATION + "/" + str(update.from_user.id) + ".jpg"
    youtube_dl_url = update.message.reply_to_message.text
    custom_file_name = None # Initialize custom_file_name to None

    if "|" in youtube_dl_url:
        url_parts = youtube_dl_url.split("|")
        if len(url_parts) >= 2: # Allow for custom filename
            youtube_dl_url = url_parts[0]
            if len(url_parts) > 1:
                custom_file_name = url_parts[1] # Get custom filename if provided
        else: # if only '|' but no custom filename after
            for entity in update.message.reply_to_message.entities:
                if entity.type == "text_link":
                    youtube_dl_url = entity.url
                elif entity.type == "url":
                    o = entity.offset
                    l = entity.length
                    youtube_dl_url = youtube_dl_url[o:o + l]
    else:
        for entity in update.message.reply_to_message.entities:
            if entity.type == "text_link":
                youtube_dl_url = entity.url
            elif entity.type == "url":
                o = entity.offset
                l = entity.length
                youtube_dl_url = youtube_dl_url[o:o + l]

    if youtube_dl_url is not None:
        youtube_dl_url = youtube_dl_url.strip()
    if custom_file_name is not None: # Handle case where custom_file_name was provided
        custom_file_name = custom_file_name.strip()
    else:
        custom_file_name = os.path.basename(youtube_dl_url) # Default to URL basename if no custom name

    description = Translation.CUSTOM_CAPTION_UL_FILE
    start = datetime.now()
    await update.message.edit_caption(
        caption=Translation.DOWNLOAD_START,
        parse_mode=enums.ParseMode.HTML
    )
    tmp_directory_for_each_user = Config.DOWNLOAD_LOCATION + "/" + str(update.from_user.id)
    os.makedirs(tmp_directory_for_each_user, exist_ok=True) # Ensure directory exists

    # Construct yt-dlp command - Playlist and single video handling
    command_to_exec = [
        "yt-dlp",
        "--cookies", "cookies.txt", # Add cookies support
        "-c",
        "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
        "--embed-subs", # Keep embed subs
        "-f", f"{youtube_dl_format}bestvideo+bestaudio/best", # Video format
        "--hls-prefer-ffmpeg", # Keep hls prefer ffmpeg
        youtube_dl_url, # URL to download
        "-o", os.path.join(tmp_directory_for_each_user, '%(title)s_%(id)s_' + youtube_dl_format + '.' + youtube_dl_ext)  # Output pattern for playlist and single files
    ]

    if tg_send_type == "audio":
        command_to_exec = [
            "yt-dlp",
            "--cookies", "cookies.txt", # Add cookies support for audio as well
            "-c",
            "--max-filesize", str(Config.TG_MAX_FILE_SIZE),
            "--bidi-workaround", # Keep bidi workaround
            "--extract-audio",
            "--audio-format", youtube_dl_ext,
            "--audio-quality", youtube_dl_format, # Audio format & quality
            youtube_dl_url,
            "-o", os.path.join(tmp_directory_for_each_user, '%(title)s_%(id)s_audio_' + youtube_dl_format + '.' + youtube_dl_ext) # Output pattern for audio
        ]

    if Config.HTTP_PROXY:
        command_to_exec.extend(["--proxy", Config.HTTP_PROXY])

    command_to_exec.append("--no-warnings") # Keep no warnings

    logger.info(command_to_exec)
    process = await asyncio.create_subprocess_exec(
        *command_to_exec,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    e_response = stderr.decode().strip()
    t_response = stdout.decode().strip()
    logger.info(e_response)
    logger.info(t_response)

    ad_string_to_replace = "**Invalid link !**" # Error string, keep as is
    if e_response and ad_string_to_replace in e_response:
        error_message = e_response.replace(ad_string_to_replace, "")
        await update.message.edit_caption(
            text=error_message
        )
        return False

    if t_response:
        logger.info(t_response)
        playlist_downloaded = False # Flag to check if playlist was downloaded
        if "Deleting matching output file" in t_response or "playlist" in t_response.lower(): # Basic playlist detection
            playlist_downloaded = True

        end_one = datetime.now()
        time_taken_for_download = (end_one - start).seconds

        await update.message.edit_caption(
            caption=Translation.UPLOAD_START,
            parse_mode=enums.ParseMode.HTML
        )

        if playlist_downloaded: # Handle Playlist Upload - upload all files in the directory
            uploaded_count = 0
            for filename in os.listdir(tmp_directory_for_each_user):
                download_directory = os.path.join(tmp_directory_for_each_user, filename)
                if not os.path.isfile(download_directory): # Only process files
                    continue

                file_size = os.stat(download_directory).st_size
                if file_size > Config.TG_MAX_FILE_SIZE:
                    try:
                        os.remove(download_directory) # Clean up large file
                    except:
                        pass # Ignore errors during cleanup
                    await bot.send_message(
                        chat_id=update.message.chat.id,
                        text=Translation.RCHD_TG_API_LIMIT_PL.format(filename, humanbytes(file_size)), # Playlist specific limit message
                        parse_mode=enums.ParseMode.HTML
                    )
                    continue # Skip to next file

                start_time = time.time()
                try:
                    if (await db.get_upload_as_doc(update.from_user.id)) is False:
                        thumbnail = await Gthumb01(bot, update) # Generate thumbnail
                        await bot.send_document( # Send as document
                            chat_id=update.message.chat.id,
                            document=download_directory,
                            thumb=thumbnail,
                            caption=description,
                            parse_mode=enums.ParseMode.HTML,
                            progress=progress_for_pyrogram,
                            progress_args=(
                                Translation.UPLOAD_START,
                                update.message,
                                start_time
                            )
                        )
                    else:
                        width, height, duration = await Mdata01(download_directory) # Get video metadata
                        thumb_image_path = await Gthumb02(bot, update, duration, download_directory) # Generate video thumbnail
                        await bot.send_video( # Send as video
                            chat_id=update.message.chat.id,
                            video=download_directory,
                            caption=description,
                            duration=duration,
                            width=width,
                            height=height,
                            supports_streaming=True,
                            parse_mode=enums.ParseMode.HTML,
                            thumb=thumb_image_path,
                            progress=progress_for_pyrogram,
                            progress_args=(
                                Translation.UPLOAD_START,
                                update.message,
                                start_time
                            )
                        )
                    uploaded_count += 1 # Increment uploaded file count
                except Exception as e:
                    logger.error(f"Error uploading file {filename}: {e}")
                finally:
                    try:
                        os.remove(download_directory) # Clean up file after upload
                        os.remove(thumb_image_path) # Clean up thumbnail
                    except:
                        pass # Ignore cleanup errors

            end_two = datetime.now()
            time_taken_for_upload = (end_two - end_one).seconds
            await update.message.edit_caption(
                caption=Translation.AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS_PL.format(uploaded_count, time_taken_for_download, time_taken_for_upload), # Playlist success message
                parse_mode=enums.ParseMode.HTML
            )
            logger.info(f"✅ Playlist downloaded and uploaded. Files: {uploaded_count}, Downloaded in: {time_taken_for_download} seconds, Uploaded in: {time_taken_for_upload} seconds")


        else: # Single File Upload Logic (original logic mostly kept)
            download_directory_single = os.path.join(tmp_directory_for_each_user, custom_file_name) # Construct single file path
            if not os.path.exists(download_directory_single): # Try to find downloaded file if custom name failed
                download_directory_single = next((os.path.join(tmp_directory_for_each_user, f) for f in os.listdir(tmp_directory_for_each_user) if os.path.isfile(os.path.join(tmp_directory_for_each_user, f))), None)

            if download_directory_single and os.path.exists(download_directory_single): # Check if download_directory_single is valid
                file_size = os.stat(download_directory_single).st_size
                if file_size > Config.TG_MAX_FILE_SIZE:
                    await update.message.edit_caption(
                        caption=Translation.RCHD_TG_API_LIMIT,
                        parse_mode=enums.ParseMode.HTML
                    )
                else:
                    start_time = time.time()
                    try:
                        if (await db.get_upload_as_doc(update.from_user.id)) is False:
                            thumbnail = await Gthumb01(bot, update)
                            await update.message.reply_document(
                                document=download_directory_single,
                                thumb=thumbnail,
                                caption=description,
                                parse_mode=enums.ParseMode.HTML,
                                progress=progress_for_pyrogram,
                                progress_args=(
                                    Translation.UPLOAD_START,
                                    update.message,
                                    start_time
                                )
                            )
                        else:
                            width, height, duration = await Mdata01(download_directory_single)
                            thumb_image_path = await Gthumb02(bot, update, duration, download_directory_single)
                            await update.message.reply_video(
                                video=download_directory_single,
                                caption=description,
                                duration=duration,
                                width=width,
                                height=height,
                                supports_streaming=True,
                                parse_mode=enums.ParseMode.HTML,
                                thumb=thumb_image_path,
                                progress=progress_for_pyrogram,
                                progress_args=(
                                    Translation.UPLOAD_START,
                                    update.message,
                                    start_time
                                )
                            )
                        if tg_send_type == "audio":
                            duration = await Mdata03(download_directory_single)
                            thumbnail = await Gthumb01(bot, update)
                            await update.message.reply_audio(
                                audio=download_directory_single,
                                caption=description,
                                parse_mode=enums.ParseMode.HTML,
                                duration=duration,
                                thumb=thumbnail,
                                progress=progress_for_pyrogram,
                                progress_args=(
                                    Translation.UPLOAD_START,
                                    update.message,
                                    start_time
                                )
                            )
                        elif tg_send_type == "vm":
                            width, duration = await Mdata02(download_directory_single)
                            thumbnail = await Gthumb02(bot, update, duration, download_directory_single)
                            await update.message.reply_video_note(
                                video_note=download_directory_single,
                                duration=duration,
                                length=width,
                                thumb=thumbnail,
                                progress=progress_for_pyrogram,
                                progress_args=(
                                    Translation.UPLOAD_START,
                                    update.message,
                                    start_time
                                )
                            )
                        else:
                            logger.info("✅ " + custom_file_name) # Log single file success

                        end_two = datetime.now()
                        time_taken_for_upload = (end_two - end_one).seconds
                        await update.message.edit_caption(
                            caption=Translation.AFTER_SUCCESSFUL_UPLOAD_MSG_WITH_TS.format(time_taken_for_download, time_taken_for_upload),
                            parse_mode=enums.ParseMode.HTML
                        )
                        logger.info(f"✅ Downloaded in: {time_taken_for_download} seconds")
                        logger.info(f"✅ Uploaded in: {time_taken_for_upload} seconds")
                    finally: # Cleanup for single file always
                        try:
                            shutil.rmtree(tmp_directory_for_each_user) # Clean up directory for single file
                            os.remove(thumbnail)
                        except Exception as e:
                            logger.error(f"Error cleaning up: {e}")
            else: # If download_directory_single is not valid after download
                await update.message.edit_caption(
                    caption=Translation.NO_VOID_FORMAT_FOUND.format("Download Failed - File not found"), # Indicate download failure if file missing
                    parse_mode=enums.ParseMode.HTML
                )
    else: # If initial yt-dlp process failed (t_response is empty)
        await update.message.edit_caption(
            caption=Translation.NO_VOID_FORMAT_FOUND.format("Incorrect Link or yt-dlp error"), # General error message
            parse_mode=enums.ParseMode.HTML
        )


# Main handler to dispatch callbacks based on the update data - keep as is
async def button(bot, update):
    if "|" in update.data:
        await youtube_dl_call_back(bot, update) # Assuming youtube_dl_call_back is still used for other buttons if needed
    elif "=" in update.data:
        await ddl_call_back(bot, update) # ddl_call_back now handles yt-dlp for direct and playlist links
    else:
        await update.message.delete()

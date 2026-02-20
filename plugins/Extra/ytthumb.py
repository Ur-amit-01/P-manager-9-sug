import os
import ytthumb
from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InputMediaPhoto,
    LinkPreviewOptions,
)

for quality in ytthumb.qualities():
    START_TEXT += f"\n  - {quality}: {ytthumb.qualities()[quality]}"

BUTTON = [InlineKeyboardButton("Feedback", url="https://telegram.me/FayasNoushad")]

photo_buttons = InlineKeyboardMarkup(
    [[InlineKeyboardButton("Other Qualities", callback_data="qualities")], BUTTON]
)


@Bot.on_callback_query()
async def cb_data(_, message):
    data = message.data.lower()
    if data == "qualities":
        await message.answer("Select a quality")
        buttons = []
        for quality in ytthumb.qualities():
            buttons.append(
                InlineKeyboardButton(
                    text=ytthumb.qualities()[quality], callback_data=quality
                )
            )
        await message.edit_message_reply_markup(
            InlineKeyboardMarkup(
                [[buttons[0], buttons[1]], [buttons[2], buttons[3]], BUTTON]
            )
        )
    elif data == "back":
        await message.edit_message_reply_markup(photo_buttons)
    elif data in ytthumb.qualities():
        thumbnail = ytthumb.thumbnail(
            video=message.message.reply_to_message.text.split(" | ")[0],
            quality=message.data,
        )
        await message.answer("Updating")
        await message.edit_message_media(
            media=InputMediaPhoto(media=thumbnail), reply_markup=photo_buttons
        )
        await message.answer("Updated Successfully")

@Bot.on_message(filters.private & filters.text)
async def send_thumbnail(bot, message):
    reply = await message.reply_text(text="`Analysing...`", quote=True)
    try:
        if " | " in message.text:
            video = message.text.split(" | ", -1)[0]
            quality = message.text.split(" | ", -1)[1]
        else:
            video = message.text
            quality = "sd"
        thumbnail = ytthumb.thumbnail(video=video, quality=quality)
        print(thumbnail)
        await message.reply_photo(
            photo=thumbnail, reply_markup=photo_buttons, quote=True
        )
        await reply.delete()
    except Exception as error:
        await reply.edit_text(
            text=error,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            reply_markup=InlineKeyboardMarkup([BUTTON]),
        )

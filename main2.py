import logging
import requests
from config import *
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackContext, CallbackQueryHandler, CommandHandler, MessageHandler, filters


# Set up logging
logging.basicConfig(level=logging.INFO)

# CoinMarketCap API URL
CMC_API_URL = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest'


def get_top_cryptocurrencies():
    params = {
        'start': '1',
        'limit': '10',
        'convert': 'USD'
    }
    headers = {
        'X-CMC_PRO_API_KEY': CMC_API_KEY
    }
    response = requests.get(CMC_API_URL, params=params, headers=headers)
    data = response.json()

    if 'data' in data:
        cryptocurrencies = data['data']
        return cryptocurrencies
    else:
        return None


async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Get Prices", callback_data='prices')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text="Welcome to the CryptoBot! Please click the button below "
                                                         "to get the latest cryptocurrency prices:",
                                   reply_markup=reply_markup)


async def prices(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    cryptocurrencies = get_top_cryptocurrencies()

    if cryptocurrencies:
        message = "Latest cryptocurrency prices:\n\n"
        for crypto in cryptocurrencies:
            name = crypto['name']
            symbol = crypto['symbol']
            price = crypto['quote']['USD']['price']
            message += f"{name} ({symbol}): ${price:.2f}\n"
    else:
        message = "Failed to fetch cryptocurrency prices."

    await context.bot.send_message(chat_id=chat_id, text=message)


async def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    data = query.data

    if data == 'prices':
        await query.answer()
        await prices(update, context)


async def handle_message(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    text = update.message.text.lower().rstrip('?')  # Remove question mark from the end of the text

    match text:
        case 'hello':
            await context.bot.send_message(chat_id=chat_id, text="Hello! How can I assist you?")
        case 'how are you':
            await context.bot.send_message(chat_id=chat_id, text="I'm a bot, but thank you for asking!")
        case 'what can you do':
            await context.bot.send_message(chat_id=chat_id,
                                           text="I can give you the prices of the top 10 latest cryptocurrencies!")
        case _:
            await context.bot.send_message(chat_id=chat_id, text="Sorry, I didn't understand that.")


def main():
    print('Starting...')

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('prices', prices))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))  # To handle any text input as start command

    app.run_polling(poll_interval=5)


if __name__ == '__main__':
    main()

import logging
import requests
from config import *
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackContext, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import json
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)


# Initialize portfolio storage
def load_portfolio(user_id):
    filename = f'data/portfolio_{user_id}.json'
    if os.path.exists(filename):
        with open(filename, 'r') as file:
            return json.load(file)
    else:
        portfolio = {'holdings': {}, 'transactions': []}
        save_portfolio(user_id, portfolio)
        return portfolio


def save_portfolio(user_id, portfolio):
    filename = f'data/portfolio_{user_id}.json'
    with open(filename, 'w') as file:
        json.dump(portfolio, file)


# Function to get top cryptocurrencies
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


# Function to get the price of a specific cryptocurrency
def get_crypto_price(crypto_id, vs_currency='USD'):
    url = 'https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest'
    params = {
        'symbol': crypto_id,
        'convert': vs_currency
    }
    headers = {
        'X-CMC_PRO_API_KEY': CMC_API_KEY
    }
    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        return data['data'][crypto_id]['quote'][vs_currency]['price']
    else:
        return None


# Start command handler
async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Get Prices", callback_data='prices')],
        [InlineKeyboardButton("Add to Portfolio", callback_data='add_to_portfolio')],
        [InlineKeyboardButton("Remove from Portfolio", callback_data='remove_from_portfolio')],
        [InlineKeyboardButton("View Portfolio", callback_data='view_portfolio')],
        [InlineKeyboardButton("View Transaction History", callback_data='view_transactions')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(chat_id=chat_id, text="Welcome to the CryptoBot! Please choose an option:", reply_markup=reply_markup)


# Prices command handler
async def prices(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    cryptocurrencies = get_top_cryptocurrencies()

    if cryptocurrencies:
        message = "Latest cryptocurrency prices:\n\n"
        for crypto in cryptocurrencies:
            name = crypto['name']
            symbol = crypto['symbol']
            price = crypto['quote']['USD']['price']
            message += f"{name} ({symbol}): ${price:,.2f}\n"
    else:
        message = "Failed to fetch cryptocurrency prices."

    await context.bot.send_message(chat_id=chat_id, text=message)


# Handle button clicks
async def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    if data == 'prices':
        await query.answer()
        await prices(update, context)
    elif data == 'add_to_portfolio':
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text='Please enter the cryptocurrency symbol and amount to add (e.g., BTC 0.5):')
        context.user_data['waiting_for_addition'] = True
    elif data == 'remove_from_portfolio':
        await query.answer()
        await context.bot.send_message(chat_id=chat_id, text='Please enter the cryptocurrency symbol and amount to remove (e.g., BTC 0.5):')
        context.user_data['waiting_for_removal'] = True
    elif data == 'view_portfolio':
        await query.answer()
        await view_portfolio(update, context)
    elif data == 'view_transactions':
        await query.answer()
        await view_transactions(update, context)


# Handle text messages
async def handle_text(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if context.user_data.get('waiting_for_addition'):
        try:
            text = update.message.text.strip().upper()
            symbol, amount = text.split()
            amount = float(amount)

            # Add to portfolio
            if symbol in portfolio['holdings']:
                portfolio['holdings'][symbol] += amount
            else:
                portfolio['holdings'][symbol] = amount

            # Record transaction
            price = get_crypto_price(symbol)
            portfolio['transactions'].append({
                'type': 'add',
                'symbol': symbol,
                'amount': amount,
                'price': price,
                'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            })

            save_portfolio(user_id, portfolio)
            context.user_data['waiting_for_addition'] = False

            await context.bot.send_message(chat_id=chat_id, text=f'Added {amount} {symbol} to your portfolio at ${price:,.2f} each.')
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text='Invalid format. Please enter the cryptocurrency symbol and amount (e.g., BTC 0.5).')
    elif context.user_data.get('waiting_for_removal'):
        try:
            text = update.message.text.strip().upper()
            symbol, amount = text.split()
            amount = float(amount)

            # Remove from portfolio
            if symbol in portfolio['holdings'] and portfolio['holdings'][symbol] >= amount:
                portfolio['holdings'][symbol] -= amount

                # Record transaction
                price = get_crypto_price(symbol)
                portfolio['transactions'].append({
                    'type': 'remove',
                    'symbol': symbol,
                    'amount': amount,
                    'price': price,
                    'timestamp': datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
                })

                save_portfolio(user_id, portfolio)
                context.user_data['waiting_for_removal'] = False

                await context.bot.send_message(chat_id=chat_id, text=f'Removed {amount} {symbol} from your portfolio at ${price:,.2f} each.')
            else:
                await context.bot.send_message(chat_id=chat_id, text='Invalid amount. You do not have enough of that cryptocurrency in your portfolio.')
        except ValueError:
            await context.bot.send_message(chat_id=chat_id, text='Invalid format. Please enter the cryptocurrency symbol and amount (e.g., BTC 0.5).')


# View portfolio command handler
async def view_portfolio(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if portfolio['holdings']:
        message = "Your portfolio:\n\n"
        total_value = 0
        for symbol, amount in portfolio['holdings'].items():
            price = get_crypto_price(symbol)
            if price is not None:
                value = price * amount
                total_value += value
                message += f"{symbol}: {amount} (${value:,.2f})\n"
            else:
                message += f"{symbol}: {amount} (price unavailable)\n"

        message += f"\nTotal portfolio value: ${total_value:,.2f}"
    else:
        message = "Your portfolio is empty."

    await context.bot.send_message(chat_id=chat_id, text=message)


# View transaction history command handler
async def view_transactions(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if portfolio['transactions']:
        message = "Your transaction history:\n\n"
        for transaction in portfolio['transactions']:
            timestamp = datetime.strptime(transaction['timestamp'], '%Y-%m-%d %H:%M:%S')
            formatted_timestamp = timestamp.strftime('%b %d, %Y %I:%M %p')
            message += f"{formatted_timestamp}: {transaction['type'].capitalize()} {transaction['amount']} {transaction['symbol']} at ${transaction['price']:,.2f} each\n"
    else:
        message = "You have no transactions in your history."

    await context.bot.send_message(chat_id=chat_id, text=message)


# Main function
def main():
    print('Starting...')

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('prices', prices))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(poll_interval=5)


if __name__ == '__main__':
    main()

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime, timezone

import requests
from flask import Flask, abort, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CallbackContext, CallbackQueryHandler, CommandHandler, MessageHandler, filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

try:
    from config import CMC_API_KEY, CMC_API_URL, TELEGRAM_TOKEN
except ImportError:
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
    CMC_API_KEY = os.environ["CMC_API_KEY"]
    CMC_API_URL = os.environ.get(
        "CMC_API_URL",
        "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest",
    )

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

QUOTES_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest"

_loop_holder: dict[str, asyncio.AbstractEventLoop] = {}
_loop_ready = threading.Event()
_loop_lock = threading.Lock()


def _portfolio_path(user_id: int) -> str:
    return os.path.join(DATA_DIR, f"portfolio_{user_id}.json")


def load_portfolio(user_id: int) -> dict:
    path = _portfolio_path(user_id)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    portfolio = {"holdings": {}, "transactions": []}
    save_portfolio(user_id, portfolio)
    return portfolio


def save_portfolio(user_id: int, portfolio: dict) -> None:
    path = _portfolio_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(portfolio, f, indent=2)


def get_top_cryptocurrencies():
    params = {"start": "1", "limit": "10", "convert": "USD"}
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    try:
        response = requests.get(CMC_API_URL, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("listings request failed: %s", e)
        return None

    if "data" in data:
        return data["data"]
    return None


def get_crypto_price(symbol: str, vs_currency: str = "USD"):
    symbol = symbol.strip().upper()
    params = {"symbol": symbol, "convert": vs_currency}
    headers = {"X-CMC_PRO_API_KEY": CMC_API_KEY}
    try:
        response = requests.get(QUOTES_URL, headers=headers, params=params, timeout=30)
        if response.status_code != 200:
            return None
        data = response.json()
        coin = data.get("data", {}).get(symbol)
        if not coin:
            return None
        return coin["quote"][vs_currency]["price"]
    except (requests.RequestException, KeyError, ValueError, TypeError) as e:
        logger.warning("quote for %s failed: %s", symbol, e)
        return None


def _format_price(p) -> str:
    if p is None:
        return "N/A"
    return f"${p:,.2f}"


async def start(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    keyboard = [
        [InlineKeyboardButton("Get Prices", callback_data="prices")],
        [InlineKeyboardButton("Add to Portfolio", callback_data="add_to_portfolio")],
        [InlineKeyboardButton("Remove from Portfolio", callback_data="remove_from_portfolio")],
        [InlineKeyboardButton("View Portfolio", callback_data="view_portfolio")],
        [InlineKeyboardButton("View Transaction History", callback_data="view_transactions")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await context.bot.send_message(
        chat_id=chat_id,
        text="Welcome to CryptoPal. Choose an option:",
        reply_markup=reply_markup,
    )


async def prices(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    cryptocurrencies = get_top_cryptocurrencies()

    if cryptocurrencies:
        message = "Latest cryptocurrency prices:\n\n"
        for crypto in cryptocurrencies:
            name = crypto["name"]
            symbol = crypto["symbol"]
            price = crypto["quote"]["USD"]["price"]
            message += f"{name} ({symbol}): ${price:,.2f}\n"
    else:
        message = "Failed to fetch cryptocurrency prices."

    await context.bot.send_message(chat_id=chat_id, text=message)


async def view_portfolio(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if portfolio["holdings"]:
        message = "Your portfolio:\n\n"
        total_value = 0.0
        for symbol, amount in portfolio["holdings"].items():
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


async def view_transactions(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if portfolio["transactions"]:
        message = "Your transaction history:\n\n"
        for transaction in portfolio["transactions"]:
            ts_raw = transaction["timestamp"]
            timestamp = datetime.strptime(ts_raw, "%Y-%m-%d %H:%M:%S")
            formatted_timestamp = timestamp.strftime("%b %d, %Y %I:%M %p")
            p = transaction.get("price")
            price_s = _format_price(p)
            message += (
                f"{formatted_timestamp}: {transaction['type'].capitalize()} "
                f"{transaction['amount']} {transaction['symbol']} at {price_s} each\n"
            )
    else:
        message = "You have no transactions in your history."

    await context.bot.send_message(chat_id=chat_id, text=message)


async def handle_button(update: Update, context: CallbackContext):
    query = update.callback_query
    if not query or not query.message:
        return
    chat_id = query.message.chat_id
    data = query.data

    if data == "prices":
        await query.answer()
        await prices(update, context)
    elif data == "add_to_portfolio":
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="Enter symbol and amount to add (e.g. BTC 0.5):",
        )
        context.user_data["waiting_for_addition"] = True
    elif data == "remove_from_portfolio":
        await query.answer()
        await context.bot.send_message(
            chat_id=chat_id,
            text="Enter symbol and amount to remove (e.g. BTC 0.5):",
        )
        context.user_data["waiting_for_removal"] = True
    elif data == "view_portfolio":
        await query.answer()
        await view_portfolio(update, context)
    elif data == "view_transactions":
        await query.answer()
        await view_transactions(update, context)


async def handle_text(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    portfolio = load_portfolio(user_id)

    if context.user_data.get("waiting_for_addition"):
        try:
            text = update.message.text.strip().upper()
            symbol, amount_s = text.split()
            amount = float(amount_s)

            if symbol in portfolio["holdings"]:
                portfolio["holdings"][symbol] += amount
            else:
                portfolio["holdings"][symbol] = amount

            price = get_crypto_price(symbol)
            portfolio["transactions"].append(
                {
                    "type": "add",
                    "symbol": symbol,
                    "amount": amount,
                    "price": price,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )

            save_portfolio(user_id, portfolio)
            context.user_data["waiting_for_addition"] = False

            await context.bot.send_message(
                chat_id=chat_id,
                text=f"Added {amount} {symbol}. Price at time: {_format_price(price)} each.",
            )
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Invalid format. Use: SYMBOL AMOUNT (e.g. BTC 0.5).",
            )
    elif context.user_data.get("waiting_for_removal"):
        try:
            text = update.message.text.strip().upper()
            symbol, amount_s = text.split()
            amount = float(amount_s)

            if symbol in portfolio["holdings"] and portfolio["holdings"][symbol] >= amount:
                portfolio["holdings"][symbol] -= amount
                if portfolio["holdings"][symbol] <= 0:
                    del portfolio["holdings"][symbol]

                price = get_crypto_price(symbol)
                portfolio["transactions"].append(
                    {
                        "type": "remove",
                        "symbol": symbol,
                        "amount": amount,
                        "price": price,
                        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

                save_portfolio(user_id, portfolio)
                context.user_data["waiting_for_removal"] = False

                await context.bot.send_message(
                    chat_id=chat_id,
                    text=f"Removed {amount} {symbol}. Price at time: {_format_price(price)} each.",
                )
            else:
                await context.bot.send_message(
                    chat_id=chat_id,
                    text="You don't hold enough of that asset to remove this amount.",
                )
        except ValueError:
            await context.bot.send_message(
                chat_id=chat_id,
                text="Invalid format. Use: SYMBOL AMOUNT (e.g. BTC 0.5).",
            )
    else:
        await start(update, context)


def build_application() -> Application:
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("prices", prices))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


ptb_application = build_application()


def _run_bot_event_loop(application: Application) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop_holder["loop"] = loop

    async def runner():
        await application.initialize()
        await application.start()
        _loop_ready.set()
        await asyncio.Future()

    try:
        loop.run_until_complete(runner())
    except Exception:
        logger.exception("Telegram bot event loop stopped")
        raise


def ensure_bot_loop_running(application: Application) -> asyncio.AbstractEventLoop:
    with _loop_lock:
        if _loop_ready.is_set() and "loop" in _loop_holder:
            return _loop_holder["loop"]

        thread = threading.Thread(
            target=_run_bot_event_loop,
            args=(application,),
            name="cryptobot-async",
            daemon=True,
        )
        thread.start()
        if not _loop_ready.wait(timeout=120):
            raise RuntimeError("Timed out waiting for Telegram bot to start")

    return _loop_holder["loop"]


def create_flask_app(application: Application) -> Flask:
    webhook_secret = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not webhook_secret:
        logger.warning("WEBHOOK_SECRET is empty; webhook route will reject all requests.")

    app = Flask(__name__)

    @app.post("/webhook/<token>")
    def telegram_webhook(token: str):
        if not webhook_secret or token != webhook_secret:
            abort(403)
        ensure_bot_loop_running(application)
        payload = request.get_json(force=True, silent=False)
        update = Update.de_json(payload, application.bot)
        loop = _loop_holder["loop"]
        fut = asyncio.run_coroutine_threadsafe(application.process_update(update), loop)
        fut.result(timeout=60)
        return "", 200

    @app.get("/")
    def health():
        return "CryptoPal: POST /webhook/<your WEBHOOK_SECRET from env>"

    return app


flask_app: Flask | None
if os.environ.get("CRYPTOBOT_WEBHOOK", "").lower() in ("1", "true", "yes"):
    ensure_bot_loop_running(ptb_application)
    flask_app = create_flask_app(ptb_application)
else:
    flask_app = None


def _ensure_event_loop_for_polling() -> None:
    """PTB run_polling uses get_event_loop(); Python 3.12+ no longer provides a default main-thread loop."""
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


def main():
    if flask_app is not None:
        port = int(os.environ.get("PORT", "5000"))
        logger.info("Flask webhook server on 0.0.0.0:%s (set CRYPTOBOT_WEBHOOK=1)", port)
        flask_app.run(host="0.0.0.0", port=port, threaded=True)
    else:
        logger.info("Starting polling…")
        _ensure_event_loop_for_polling()
        ptb_application.run_polling(poll_interval=5)


if __name__ == "__main__":
    main()

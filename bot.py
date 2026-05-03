import logging
from binance.client import Client
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pandas as pd
import numpy as np
import ta
import config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

client = Client(config.BINANCE_API_KEY, config.BINANCE_SECRET_KEY)

stats = {sym: {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0} for sym in config.SYMBOLS}

def get_data(symbol):
    klines = client.get_klines(symbol=symbol, interval=config.TIMEFRAME, limit=100)
    df = pd.DataFrame(klines, columns=["time","open","high","low","close","volume","ct","qa","nt","tbbav","tbqav","ignore"])
    df["close"] = pd.to_numeric(df["close"])
    df["high"] = pd.to_numeric(df["high"])
    df["low"] = pd.to_numeric(df["low"])
    df["open"] = pd.to_numeric(df["open"])
    df["volume"] = pd.to_numeric(df["volume"])
    return df

def analyze(symbol):
    df = get_data(symbol)
    df["ema_fast"] = ta.trend.ema_indicator(df["close"], window=config.EMA_FAST)
    df["ema_slow"] = ta.trend.ema_indicator(df["close"], window=config.EMA_SLOW)
    df["rsi"] = ta.momentum.rsi(df["close"], window=config.RSI_PERIOD)
    df["atr"] = ta.volatility.average_true_range(df["high"], df["low"], df["close"])

    last = df.iloc[-1]
    prev = df.iloc[-2]

    close = last["close"]
    atr = last["atr"]
    sl_dist = atr * 1.5
    tp_dist = sl_dist * config.RR_RATIO

    buy = (prev["ema_fast"] < prev["ema_slow"] and last["ema_fast"] > last["ema_slow"] and last["rsi"] < config.RSI_OVERBOUGHT)
    sell = (prev["ema_fast"] > prev["ema_slow"] and last["ema_fast"] < last["ema_slow"] and last["rsi"] > config.RSI_OVERSOLD)

    if buy:
        return {"signal": "BUY", "entry": close, "sl": round(close - sl_dist, 4), "tp": round(close + tp_dist, 4), "atr": round(atr, 4)}
    elif sell:
        return {"signal": "SELL", "entry": close, "sl": round(close + sl_dist, 4), "tp": round(close - tp_dist, 4), "atr": round(atr, 4)}
    return None

async def send_signal(app, symbol, data):
    emoji = "🟢" if data["signal"] == "BUY" else "🔴"
    msg = f"{emoji} *{data['signal']} Signal — {symbol}*\n\n"
    msg += f"📍 Entry: `{data['entry']}`\n"
    msg += f"🛑 SL: `{data['sl']}`\n"
    msg += f"🎯 TP: `{data['tp']}`\n"
    msg += f"📊 ATR: `{data['atr']}`\n"
    msg += f"⚖️ Risk:Reward = 1:{config.RR_RATIO}"
    await app.bot.send_message(chat_id=config.CHAT_ID, text=msg, parse_mode="Markdown")

async def check_signals(app):
    for symbol in config.SYMBOLS:
        try:
            result = analyze(symbol)
            if result:
                await send_signal(app, symbol, result)
        except Exception as e:
            logger.error(f"Error {symbol}: {e}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"✅ Bot চালু হয়েছে!\nতোমার Chat ID: `{chat_id}`\n\nএই ID টা config.py তে CHAT_ID তে বসাও।", parse_mode="Markdown")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📊 *Trading Stats*\n\n"
    for sym, s in stats.items():
        wr = round(s["wins"] / s["trades"] * 100, 2) if s["trades"] > 0 else 0
        msg += f"*{sym}*\n"
        msg += f"Trades: {s['trades']} | W/L: {s['wins']}/{s['losses']}\n"
        msg += f"Win Rate: {wr}% | PnL: {round(s['pnl'], 2)}%\n\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def analyze_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Analyzing market...")
    for symbol in config.SYMBOLS:
        try:
            result = analyze(symbol)
            if result:
                await send_signal(app, symbol, result)
            else:
                await update.message.reply_text(f"⏳ {symbol} — No signal now")
        except Exception as e:
            await update.message.reply_text(f"❌ Error: {symbol}")

async def post_init(application):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_signals, "interval", minutes=60, args=[application])
    scheduler.start()

def main():
    global app
    app = Application.builder().token(config.TELEGRAM_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("analyze", analyze_cmd))
    app.run_polling()

if __name__ == "__main__":
    main()

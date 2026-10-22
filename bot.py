import os
import asyncio
import time
from datetime import datetime
from dotenv import load_dotenv
import ccxt.async_support as ccxt
from telegram import Bot
from aiohttp import web

load_dotenv()

# ================== CONFIG ==================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

EXCHANGE_NAME = "bybit"
TIMEFRAME = "15m"
SCAN_INTERVAL = 300          # 5 minutes
COOLDOWN = 1800              # 30 minutes

# Risk settings (you can change these later)
SL_PERCENT = 1.2             # Stop Loss % from entry
TP1_PERCENT = 1.0
TP2_PERCENT = 2.0
TP3_PERCENT = 3.0

WATCHLIST = [
    "BTC/USDT:USDT",
    "ETH/USDT:USDT",
    "SOL/USDT:USDT",
    "XRP/USDT:USDT",
    "BNB/USDT:USDT",
    "DOGE/USDT:USDT",
    "ADA/USDT:USDT",
    "AVAX/USDT:USDT",
    "LINK/USDT:USDT",
    "DOT/USDT:USDT",
    "MATIC/USDT:USDT",
    "LTC/USDT:USDT",
    "ATOM/USDT:USDT",
    "NEAR/USDT:USDT",
    "APT/USDT:USDT",
    "ARB/USDT:USDT",
    "OP/USDT:USDT",
    "SUI/USDT:USDT",
    "PEPE/USDT:USDT",
    "WIF/USDT:USDT",
]

# ============================================

bot = Bot(token=TELEGRAM_BOT_TOKEN)
last_signals = {}

def create_exchange():
    if EXCHANGE_NAME == "bybit":
        return ccxt.bybit({
            "enableRateLimit": True,
            "options": {"defaultType": "swap"}
        })
    else:
        return ccxt.binanceusdm({
            "enableRateLimit": True,
            "options": {"defaultType": "future"}
        })

def calculate_ema(prices, period):
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, len(prices)):
        change = prices[i] - prices[i-1]
        gains.append(max(change, 0))
        losses.append(abs(min(change, 0)))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

async def get_ohlcv(exchange, symbol):
    try:
        ohlcv = await exchange.fetch_ohlcv(symbol, TIMEFRAME, limit=50)
        closes = [candle[4] for candle in ohlcv]
        return closes
    except Exception as e:
        print(f"Error fetching {symbol}: {e}")
        return None

async def generate_signal(closes):
    if not closes or len(closes) < 30:
        return None
    ema9 = calculate_ema(closes, 9)
    ema21 = calculate_ema(closes, 21)
    rsi = calculate_rsi(closes, 14)
    if ema9 is None or ema21 is None or rsi is None:
        return None
    if ema9 > ema21 and rsi < 70:
        return "BUY"
    elif ema9 < ema21 and rsi > 30:
        return "SELL"
    return None

def calculate_levels(entry, signal):
    if signal == "BUY":
        sl = entry * (1 - SL_PERCENT / 100)
        tp1 = entry * (1 + TP1_PERCENT / 100)
        tp2 = entry * (1 + TP2_PERCENT / 100)
        tp3 = entry * (1 + TP3_PERCENT / 100)
    else:  # SELL
        sl = entry * (1 + SL_PERCENT / 100)
        tp1 = entry * (1 - TP1_PERCENT / 100)
        tp2 = entry * (1 - TP2_PERCENT / 100)
        tp3 = entry * (1 - TP3_PERCENT / 100)
    return sl, tp1, tp2, tp3

async def send_signal(symbol, signal, price, rsi):
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    emoji = "🟢 BUY" if signal == "BUY" else "🔴 SELL"
    clean_symbol = symbol.replace(":USDT", "")

    sl, tp1, tp2, tp3 = calculate_levels(price, signal)

    message = f"""
{emoji} SIGNAL

Pair: {clean_symbol}
Entry: {price:.4f}
Stop Loss: {sl:.4f}
Take Profit 1: {tp1:.4f}
Take Profit 2: {tp2:.4f}
Take Profit 3: {tp3:.4f}

RSI: {rsi:.1f}
Timeframe: {TIMEFRAME}
Exchange: {EXCHANGE_NAME.upper()}
Time: {now}

Strategy: EMA 9/21 + RSI
"""
    try:
        await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message)
        print(f"Signal sent: {signal} {symbol} @ {price}")
    except Exception as e:
        print(f"Telegram error: {e}")

async def scan_market():
    exchange = create_exchange()
    print(f"[{datetime.utcnow()}] Scanning {EXCHANGE_NAME.upper()} market...")
    try:
        for symbol in WATCHLIST:
            closes = await get_ohlcv(exchange, symbol)
            if not closes:
                continue
            signal = await generate_signal(closes)
            if not signal:
                continue
            key = f"{symbol}_{signal}"
            now = time.time()
            if key in last_signals and now - last_signals[key] < COOLDOWN:
                continue
            price = closes[-1]
            rsi = calculate_rsi(closes, 14)
            await send_signal(symbol, signal, price, rsi)
            last_signals[key] = now
            await asyncio.sleep(1)
    finally:
        await exchange.close()

# ========== Keep-alive web server ==========
async def handle(request):
    return web.Response(text="Futures Signal Bot is running ✅")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"Web server started on port {port}")

# ========== Main ==========
async def main():
    print("=" * 40)
    print("Futures Signal Bot Started")
    print(f"Exchange : {EXCHANGE_NAME.upper()}")
    print(f"Pairs    : {len(WATCHLIST)}")
    print(f"Timeframe: {TIMEFRAME}")
    print("=" * 40)

    await start_web_server()

    try:
        await bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="🤖 Futures Signal Bot is now ONLINE and scanning the market..."
        )
    except Exception as e:
        print(f"Could not send startup message: {e}")

    while True:
        try:
            await scan_market()
        except Exception as e:
            print(f"Main loop error: {e}")
        await asyncio.sleep(SCAN_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())

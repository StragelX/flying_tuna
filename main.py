import logging
import asyncio
import os
import sqlite3
from datetime import datetime
from ryanair import Ryanair
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# --- SETTINGS ---
API_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHECK_INTERVAL_HOURS = 2
MAX_FLIGHTS = 2

# Initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# ryanair-py 3.x: only get_cheapest_flights(origin, date_from, date_to, destination_airport=...)
api = Ryanair(currency="EUR")
scheduler = AsyncIOScheduler()


def _flight_number(flight) -> str:
    """Flight number from ryanair-py (3.x: flightNumber, older: flight_number)."""
    return getattr(flight, 'flightNumber', None) or getattr(flight, 'flight_number', '')

# --- DATABASE OPERATIONS ---
def init_db():
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            origin TEXT,
            destination TEXT,
            date TEXT,
            flight_number TEXT,
            last_price REAL
        )
    ''')
    conn.commit()
    conn.close()

def get_tracked_flights(chat_id=None):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    if chat_id:
        cursor.execute('SELECT * FROM flights WHERE chat_id = ?', (chat_id,))
    else:
        cursor.execute('SELECT * FROM flights')
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_price(flight_id, new_price):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE flights SET last_price = ? WHERE id = ?', (new_price, flight_id))
    conn.commit()
    conn.close()

# --- PRICE CHECK LOGIC ---
async def check_prices():
    flights = get_tracked_flights()
    if not flights:
        return

    for f in flights:
        db_id, chat_id, origin, dest, date, f_number, last_price = f
        try:
            # Format date for API
            date_obj = datetime.strptime(date, '%Y-%m-%d').date()
            # get_cheapest_flights(origin, date_from, date_to, destination_airport=dest)
            trips = api.get_cheapest_flights(origin, date_obj, date_obj, destination_airport=dest)

            current_flight = next((t for t in trips if _flight_number(t) == f_number), None) if trips else None

            if current_flight:
                new_price = current_flight.price
                if new_price != last_price:
                    diff = new_price - last_price
                    direction = "📈 Up" if diff > 0 else "📉 Down"
                    msg = (f"🔔 PRICE CHANGE! {direction}\n"
                           f"Flight: {f_number} ({origin} -> {dest})\n"
                           f"Date: {date}\n"
                           f"New Price: {new_price} EUR (was {last_price} EUR)")
                    await bot.send_message(chat_id, msg)
                    update_price(db_id, new_price)
        except Exception as e:
            logging.error(f"Error checking {f_number}: {e}")

# --- BOT COMMANDS ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("✈️ **Ryanair Tracker Active**\n\n"
                         "Commands:\n"
                         "• `ADD VNO BVA 2026-05-20` - track a route\n"
                         "• `/list` - see your active tracks\n"
                         "• `/clear` - delete all your tracks")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    flights = get_tracked_flights(message.chat.id)
    if not flights:
        await message.answer("You are not tracking any flights.")
        return

    response = "📋 **Your Tracked Flights:**\n"
    for f in flights:
        response += f"• {f[5]}: {f[2]}->{f[3]} on {f[4]} (Last price: {f[6]}€)\n"
    await message.answer(response)

@dp.message(Command("clear"))
async def cmd_clear(message: types.Message):
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('DELETE FROM flights WHERE chat_id = ?', (message.chat.id,))
    conn.commit()
    conn.close()
    await message.answer("All your tracking data has been deleted.")

@dp.message()
async def handle_message(message: types.Message):
    if message.text and message.text.upper().startswith("ADD"):
        try:
            parts = message.text.split()
            if len(parts) != 4:
                await message.answer("Usage: ADD [ORIGIN] [DEST] [YYYY-MM-DD]")
                return

            _, origin, dest, date_str = parts
            origin, dest = origin.upper(), dest.upper()
            date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()

            # Check limit
            existing = get_tracked_flights(message.chat.id)
            if len(existing) >= MAX_FLIGHTS:
                await message.answer(f"Limit reached! Max {MAX_FLIGHTS} flights.")
                return

            # get_cheapest_flights returns at most 1 flight per route/date in 3.x
            trips = api.get_cheapest_flights(origin, date_obj, date_obj, destination_airport=dest)
            if not trips:
                await message.answer(f"No flights found for {origin}->{dest} on {date_str}.")
                return

            conn = sqlite3.connect('tracker.db')
            cursor = conn.cursor()
            for t in trips:
                cursor.execute('''
                    INSERT INTO flights (chat_id, origin, destination, date, flight_number, last_price)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (message.chat.id, origin, dest, date_str, _flight_number(t), t.price))
            conn.commit()
            conn.close()

            await message.answer(f"✅ Now tracking {len(trips)} flight(s) for {date_str}!")
        except Exception as e:
            await message.answer(f"⚠️ Error: {str(e)}")

# --- RUN ---
async def main():
    if not API_TOKEN:
        logging.error("Set TELEGRAM_BOT_TOKEN (env var or .env file).")
        raise SystemExit(1)
    init_db()
    logging.basicConfig(level=logging.INFO)
    scheduler.add_job(check_prices, "interval", hours=CHECK_INTERVAL_HOURS)
    scheduler.start()
    print("Bot is running...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())

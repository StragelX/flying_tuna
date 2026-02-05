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
MAX_FLIGHTS = 4

# Initialization
bot = Bot(token=API_TOKEN)
dp = Dispatcher()
# ryanair-py 3.x: only get_cheapest_flights(origin, date_from, date_to, destination_airport=...)
api = Ryanair(currency="EUR")
scheduler = AsyncIOScheduler()

# Ryanair origin airports to search for a flight by number (main bases + common)
RYANAIR_ORIGINS = [
    "DUB", "STN", "LTN", "BGY", "MAD", "BCN", "BVA", "CRL", "FCO", "CIA", "LIS", "OPO", "FAO",
    "VNO", "WRO", "RZE", "KTW", "POZ", "GDN", "WAW", "RIX", "TLL", "HHN", "CGN", "PRG", "BUD",
    "VIE", "BRU", "EIN", "PMI", "ALC", "AGP", "SVQ", "MXP", "VCE", "BLQ", "PSA", "NOC", "SNN",
]


def _flight_number(flight) -> str:
    """Flight number from ryanair-py (3.x: flightNumber, older: flight_number)."""
    return getattr(flight, 'flightNumber', None) or getattr(flight, 'flight_number', '')


def _normalize_flight_code(code: str) -> str:
    """Normalize user input to API format (e.g. FR1234 -> FR 1234)."""
    code = (code or "").strip().upper()
    if not code:
        return ""
    if code.startswith("FR") and len(code) > 2 and code[2] != " ":
        return f"FR {code[2:]}"
    return code

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


def delete_tracked_flight(chat_id: int, flight_code_norm: str) -> int:
    """Delete all records for this chat and flight code. Returns number of deleted rows."""
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute(
        'DELETE FROM flights WHERE chat_id = ? AND flight_number = ?',
        (chat_id, flight_code_norm),
    )
    deleted = cursor.rowcount or 0
    conn.commit()
    conn.close()
    return deleted

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
                         "• `ADD FR1234 2026-05-20` — flight + date (route found automatically)\n"
                         "• `delete FR1234` - stop tracking this flight\n"
                         "• `/list` - see your active tracks\n"
                         "• `/help` - how to add a flight\n"
                         "• `/clear` - delete all your tracks")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "📌 **Commands**\n\n"
        "`ADD [flight code] [date]`\n"
        "• Add a new flight to track. Route is found automatically.\n"
        "• Flight code — Ryanair number, e.g. `FR1234` or `FR 1234`\n"
        "• Date — departure date: `YYYY-MM-DD` (e.g. `2026-05-20`)\n"
        "Example: `ADD FR1234 2026-05-20`\n\n"
        "`delete [flight code]`\n"
        "• Stop tracking all flights with this code in this chat.\n"
        "Example: `delete FR1234`\n\n"
        "`/list`\n"
        "• Show all flights you are currently tracking.\n\n"
        "`/clear`\n"
        "• Delete all your tracking data.\n\n"
        "Flight and airport codes: ryanair.com."
    )

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

async def _find_flight_on_date(flight_code_norm: str, date_obj) -> tuple[str, str, float] | None:
    """Search Ryanair origins for this flight on date. Returns (origin, dest, price) or None."""
    for origin in RYANAIR_ORIGINS:
        try:
            trips = api.get_cheapest_flights(origin, date_obj, date_obj)
            for t in trips or []:
                if _flight_number(t) == flight_code_norm:
                    return (t.origin, t.destination, t.price)
        except Exception:
            pass
        await asyncio.sleep(0.4)  # be nice to the API
    return None


async def _do_add_flight(chat_id: int, flight_code_norm: str, date_str: str, origin: str, dest: str) -> str | None:
    """Add one flight. Returns None on success, or error message."""
    existing = get_tracked_flights(chat_id)
    if len(existing) >= MAX_FLIGHTS:
        return f"Limit reached! Max {MAX_FLIGHTS} flights."
    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return "Invalid date. Use YYYY-MM-DD."
    trips = api.get_cheapest_flights(origin, date_obj, date_obj, destination_airport=dest)
    if not trips:
        return f"No flights found for {origin}->{dest} on {date_str}."
    match = next((t for t in trips if _flight_number(t) == flight_code_norm), None)
    if not match:
        available = ", ".join(_flight_number(t) for t in trips)
        return f"Flight {flight_code_norm} not found on {date_str} for {origin}->{dest}. Available: {available}."
    conn = sqlite3.connect('tracker.db')
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO flights (chat_id, origin, destination, date, flight_number, last_price)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (chat_id, origin, dest, date_str, _flight_number(match), match.price))
    conn.commit()
    conn.close()
    return None  # success


@dp.message()
async def handle_message(message: types.Message):
    chat_id = message.chat.id
    text = (message.text or "").strip()
    upper_text = text.upper()

    try:
        # ADD command
        if upper_text.startswith("ADD"):
            parts = text.split()
            if len(parts) == 3:
                # ADD flight date
                _, flight_code, date_str = parts
                flight_code_norm = _normalize_flight_code(flight_code)
                if not flight_code_norm:
                    await message.answer("Enter a valid flight code (e.g. FR1234).")
                    return
                try:
                    date_obj = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    await message.answer("Invalid date. Use YYYY-MM-DD.")
                    return
                await message.answer("Searching for your flight…")
                found = await _find_flight_on_date(flight_code_norm, date_obj)
                if found:
                    origin, dest, price = found
                    err = await _do_add_flight(chat_id, flight_code_norm, date_str, origin, dest)
                    if err:
                        await message.answer(f"⚠️ {err}")
                    else:
                        await message.answer(
                            f"✅ Now tracking {flight_code_norm} ({origin}→{dest}) on {date_str}. Price: {price}€"
                        )
                else:
                    await message.answer(
                        f"Flight {flight_code_norm} not found on {date_str}."
                    )
                return
            await message.answer(
                "Usage: `ADD FR1234 2026-05-20`"
            )
            return

        # delete command
        if upper_text.startswith("DELETE"):
            parts = text.split()
            if len(parts) != 2:
                await message.answer("Usage: `delete FR1234`")
                return
            _, flight_code = parts
            flight_code_norm = _normalize_flight_code(flight_code)
            if not flight_code_norm:
                await message.answer("Enter a valid flight code (e.g. FR1234).")
                return
            deleted = delete_tracked_flight(chat_id, flight_code_norm)
            if deleted:
                await message.answer(f"Deleted {deleted} tracking record(s) for {flight_code_norm}.")
            else:
                await message.answer(f"You are not tracking flight {flight_code_norm}.")
            return
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

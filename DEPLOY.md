# Deploy Ryanair Price Tracker Bot to Railway

Step-by-step guide to run the bot 24/7 on Railway (free tier).

---

## 1. Put your bot token in an env var (local)

The bot reads the token from the **`TELEGRAM_BOT_TOKEN`** environment variable.

**On your PC (optional, for local run):**

- Create a file `.env` in the project folder (it is in `.gitignore`, so it won’t be committed):
  ```env
  TELEGRAM_BOT_TOKEN=your_bot_token_here
  ```
- To load it when running locally you can use `python-dotenv` and add at the top of `main.py`:
  ```python
  from dotenv import load_dotenv
  load_dotenv()
  ```
  Or set the variable in the terminal before running:
  ```powershell
  $env:TELEGRAM_BOT_TOKEN="your_token_here"
  python main.py
  ```

You will set the same variable in Railway in a later step.

---

## 2. Push the project to GitHub

1. Open [github.com](https://github.com) and sign in.
2. Click **New repository** (or **+** → **New repository**).
3. Name it (e.g. `ryanair-tracker-bot`), leave it **Public**, do **not** add README/.gitignore (you already have them). Create the repo.
4. On your PC, in the project folder, run in a terminal (if you haven’t initialized git yet):

   ```powershell
   cd c:\www\flying_tuna
   git init
   git add main.py requirements.txt .gitignore
   git commit -m "Ryanair tracker bot for Railway"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repo name.

---

## 3. Sign up / log in to Railway

1. Go to [railway.app](https://railway.app).
2. Click **Login** and sign in with **GitHub** (recommended).
3. Authorize Railway to access your GitHub account.

---

## 4. Create a new project from GitHub

1. In the Railway dashboard click **New Project**.
2. Choose **Deploy from GitHub repo**.
3. Select the repository you pushed (e.g. `ryanair-tracker-bot`).
4. Railway will create a project and try to deploy. The first deploy may fail until you set the token and start command; that’s OK.

---

## 5. Set the Telegram bot token

1. In your project, click the **service** (the box that represents your app).
2. Open the **Variables** tab.
3. Click **+ New Variable**.
4. Name: **`TELEGRAM_BOT_TOKEN`**
   Value: your bot token from [@BotFather](https://t.me/BotFather).
5. Save. Railway will redeploy automatically when you add/change variables.

---

## 6. Set the start command

1. Still in the same service, go to the **Settings** tab.
2. Find **Deploy** or **Build & Deploy** section.
3. Set **Start Command** to:
   ```bash
   python main.py
   ```
4. If there is a **Root Directory** field, leave it empty (or `/`).
5. Save. Railway will redeploy.

---

## 7. Deploy and check logs

1. Go to the **Deployments** tab.
2. Wait until the latest deployment shows **Success** (green).
3. Open **View Logs** for that deployment. You should see something like:
   ```text
   Bot is running...
   ```
4. If you see an error about `TELEGRAM_BOT_TOKEN`, double-check the variable name and value in the **Variables** tab.

---

## 8. Test the bot

1. Open Telegram and find your bot.
2. Send `/start` or `ADD FR1234 2026-05-20` (flight code and date).
3. If the bot answers, it’s running on Railway.

---

## Summary

| Step | What to do |
|------|------------|
| 1 | Use `TELEGRAM_BOT_TOKEN` for the token (e.g. in `.env` locally). |
| 2 | Push the project to a GitHub repo. |
| 3 | Sign in at [railway.app](https://railway.app) with GitHub. |
| 4 | New Project → Deploy from GitHub repo → choose your repo. |
| 5 | In the service: **Variables** → add `TELEGRAM_BOT_TOKEN` = your token. |
| 6 | **Settings** → **Start Command** = `python main.py`. |
| 7 | Check **Deployments** and **Logs** until deploy is successful. |
| 8 | Test the bot in Telegram. |

After this, the bot runs 24/7 on Railway. The free tier gives a monthly credit (about $5); this bot uses very little and usually stays within the free allowance.

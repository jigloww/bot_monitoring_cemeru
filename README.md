# Semeru Quota Telegram Bot

Bot Telegram untuk memantau ketersediaan kuota pendakian Gunung Semeru secara otomatis.

## Features

- Monitoring kuota setiap interval tertentu
- Mengirim notifikasi Telegram saat kuota tersedia
- Menyimpan state agar tidak mengirim notifikasi berulang
- Berjalan 24/7 menggunakan systemd
- Menggunakan Python Standard Library (tanpa dependency eksternal)

---

## Project Structure

```
semeru_bot/
│
├── config/
├── data/
├── logs/
├── venv/
├── .env
├── .gitignore
├── README.md
├── requirements.txt
└── semeru_quota_bot.py
```

---

## Installation

Clone repository

```bash
git clone <repository-url>
cd semeru_bot
```

Create virtual environment

```bash
python3 -m venv venv
```

Activate

```bash
source venv/bin/activate
```

---

## Environment Variables

Copy

```bash
cp config/.env.example .env
```

Fill

```
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## Run

```bash
python semeru_quota_bot.py
```

---

## Production

Restart service

```bash
sudo systemctl restart semeru-bot
```

Check status

```bash
sudo systemctl status semeru-bot
```

View logs

```bash
sudo journalctl -u semeru-bot -f
```

# Discord Autoposting Bot

Discord bot for automatic scheduled posting of images and links from a queue file. Calculates optimal posting intervals based on queue size and target completion time.

## Features

- Automatic posting from file-based queue
- Interval calculation based on remaining time and queue size
- Image embed formatting with timestamps
- State persistence across restarts
- Dynamic scheduling adjustment when new content is added
- Real-time status updates showing next post time and queue count

## Requirements

- Python 3.8+
- Discord bot token
- Discord server with appropriate permissions

## Installation

0. Note: This tutorial has not been tested yet, if you have any problems please contact me in issues.

1. Clone the repository:
```bash
cd /srv
git clone https://github.com/asvdvl/autoposting_discord_bot
cd autoposting_discord_bot
```

2. Install dependencies:
```bash
pip install dotenv discord apscheduler
```

3. Copy environment configuration:
```bash
cp .env.example .env
```

4. Edit `.env` with your settings:
```
DISCORD_TOKEN=your_bot_token_here
QUEUE_FILE=/srv/autoposting_discord_bot/links.txt
PLANNING_FOR_DAYS=7
DISCORD_CHANNEL_ID=your_channel_id
```

6. Create queue file with path QUEUE_FILE:
```bash
touch /srv/autoposting_discord_bot/links.txt
```

7. Create initial state file if you encounter `json.decoder.JSONDecodeError` errors:
```bash
echo '{}' > state.json
```

## Configuration

### Environment Variables

- `DISCORD_TOKEN`: Your Discord bot token
- `QUEUE_FILE`: Path to file containing links/images to post
- `PLANNING_FOR_DAYS`: Number of days to spread posts over (default: 7)
- `DISCORD_CHANNEL_ID`: Target channel ID (optional, uses default if not set)

### Queue File Format

Add URLs one per line:
```
https://example.com/image1.png
https://example.com/link1
<t:1234567890:f> https://example.com/image2.jpg
```

Timestamps can be included using Discord timestamp format.

If you need embeds for images, then the format is `<t: 123: f> https: // a.b/c.jpg` is required

## Systemd Service

Create `autoposting.service` by command `sudo systemctl --full --force autoposting.service` and paste this:

```ini
[Unit]
Description=Discord Autoposting Bot
After=network.target

[Service]
Type=simple
User=autoposting
Group=autoposting
WorkingDirectory=/srv/autoposting_discord_bot
Environment=PYTHONUNBUFFERED=1
ExecStart=/usr/bin/python3 /srv/autoposting_discord_bot/main.py
StandardOutput=journal
StandardError=journal
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Setup and start service:
```bash
# Create user
sudo useradd -r -s /bin/false autoposting

# Set permissions
sudo chown -R autoposting:autoposting /srv/autoposting_discord_bot
sudo chmod 666 /srv/autoposting_discord_bot/links.txt

# Enable and start service
sudo systemctl daemon-reload
sudo systemctl enable --now autoposting.service

# Check status
sudo systemctl status autoposting.service
```

## Usage

1. Add links to your queue file (one per line)
2. Start the bot
3. Bot will automatically calculate posting intervals and begin posting
4. Monitor logs via systemd or console output

## Bot Behavior

- Posts are scheduled to complete within the configured time period
- Minimum interval between posts is 5 minutes
- Adding new content while running extends the completion time
- Bot status shows next post time and remaining queue count
- Links are posted as spoiler text with queue position
- If someone will post a message with the investment in the target channel, then the post will be postponed.Made to fill the channel content when no one posts memes, if you want to disable it, you need to add Return on a 172 line, immediately after imposing the function `async def on_message`

## Troubleshooting

- If `state.json` errors occur, create file with `{}` content
- Check Discord permissions for bot in target channel
- Verify queue file exists and is readable
- Monitor systemd logs: `journalctl -u autoposting.service -f`
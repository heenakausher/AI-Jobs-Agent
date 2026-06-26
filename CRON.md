# Cron Setup — AI Jobs Agent

Run the agent daily to generate tailored CVs, cover letters, and track progress.

## 1. Find your project path

```bash
# Replace with your actual deployment path
PROJECT_PATH="/home/ubuntu/AI-Jobs-Agent"
```

## 2. Make sure deploy.sh is executable

```bash
chmod +x "$PROJECT_PATH/deploy.sh"
```

## 3. Edit crontab

```bash
crontab -e
```

## 4. Add one of these entries

**Run daily at 9:00 AM:**

```cron
0 9 * * * cd /home/ubuntu/AI-Jobs-Agent && /usr/bin/bash deploy.sh >> /home/ubuntu/AI-Jobs-Agent/agent.log 2>&1
```

**Run every Monday at 8:00 AM:**

```cron
0 8 * * 1 cd /home/ubuntu/AI-Jobs-Agent && /usr/bin/bash deploy.sh >> /home/ubuntu/AI-Jobs-Agent/agent.log 2>&1
```

**Run twice daily (8 AM & 6 PM):**

```cron
0 8,18 * * * cd /home/ubuntu/AI-Jobs-Agent && /usr/bin/bash deploy.sh >> /home/ubuntu/AI-Jobs-Agent/agent.log 2>&1
```

## 5. Verify the cron is active

```bash
crontab -l
```

## 6. Check logs

```bash
tail -f /home/ubuntu/AI-Jobs-Agent/agent.log
```

> **Note:** `main.py` already logs to `agent.log` automatically.  
> The `>>` redirect in the cron entry above is a safety net — it captures any stray stdout/stderr from the shell wrapper itself.

# Discord Message Archiver & Bulk Deleter

**Script:** `/opt/Project-Tango/scripts/discord_message_archiver.py`  
**Author:** Jeff Geronimo  
**Date:** 2026-08-18

---

## Overview

This utility archives all Discord messages from bot channels to JSON files and optionally bulk deletes messages that are less than 14 days old.

**Use Case:** Clean up test messages while preserving a complete archive for reference.

---

## Features

1. **Complete Message Archive**
   - Archives all messages from all bot channels
   - Saves to timestamped JSON files
   - Includes message content, attachments, embeds, reactions, author info
   - Preserves threading/reply relationships

2. **Bulk Deletion** (Optional)
   - Deletes messages < 14 days old (Discord API limitation)
   - Batch deletion (up to 100 messages per API call)
   - Rate-limited to avoid hitting Discord limits
   - Progress tracking

3. **Summary Reports**
   - Human-readable summary file
   - Channel-by-channel breakdown
   - Message counts and statistics

---

## Usage

### Step 1: Archive Only (No Deletion)

```bash
cd /opt/Project-Tango
source backend/venv/bin/activate
python3 scripts/discord_message_archiver.py --archive-only
```

This will:
- Archive all messages from all bot channels
- Save to `/opt/Project-Tango/archives/discord_messages/discord_archive_TIMESTAMP.json`
- Create a summary report
- **NOT delete any messages**

### Step 2: Archive + Bulk Delete

```bash
python3 scripts/discord_message_archiver.py --archive-delete
```

This will:
1. Archive all messages (same as above)
2. Wait 3 seconds (countdown)
3. Bulk delete messages < 14 days old from all channels
4. Show progress and final count

---

## Channels Processed

The script processes all bot channels:

| Channel | Channel ID | Environment Variable |
|---------|-----------|---------------------|
| admiral | `SCHUBERT_BOT_CHANNEL_ID` | 1538476446157115442 |
| architect | `ARCHITECT_CHANNEL_ID` | 1538767137080877056 |
| quartermaster | `QUARTERMASTER_CHANNEL_ID` | 1538818248542396428 |
| cartographer | `CARTOGRAPHER_CHANNEL_ID` | 1538818895706718269 |
| dr-voss | `DR_VOSS_CHANNEL_ID` | 1539104998821068880 |
| proctor | `PROCTOR_CHANNEL_ID` | 1539104999941079103 |
| cortex | `CORTEX_CHANNEL_ID` | 1539173946698498088 |
| senior-staff-meeting | `SENIOR_STAFF_CHANNEL_ID` | 1539023116968398911 |
| proctor-delegation | `PROCTOR_DELEGATION_CHANNEL_ID` | 1539159059071111190 |
| proctor-analysis | `PROCTOR_ANALYSIS_CHANNEL_ID` | 1539159060568342539 |

---

## Archive Format

### JSON Structure

```json
{
  "archive_timestamp": "20260818_193045",
  "archive_date": "2026-08-18T19:30:45.123456+00:00",
  "total_channels": 10,
  "total_messages": 1234,
  "channels": {
    "admiral": {
      "channel_id": "1538476446157115442",
      "channel_name": "admiral",
      "message_count": 150,
      "messages": [
        {
          "id": "1234567890123456789",
          "channel_id": "1538476446157115442",
          "channel_name": "admiral",
          "author_id": "1075596247966167131",
          "author_name": "themightymaven#0",
          "author_display_name": "themightymaven",
          "author_is_bot": false,
          "content": "Hello Admiral!",
          "timestamp": "2026-08-18T12:00:00.000000+00:00",
          "edited_timestamp": null,
          "attachments": [],
          "embeds": [],
          "reactions": [],
          "reference": null
        }
      ]
    }
  }
}
```

### Summary File

```
Discord Message Archive Summary
======================================================================

Archive Date: 2026-08-18T19:30:45.123456+00:00
Total Channels: 10
Total Messages Archived: 1234
Total Messages Deleted: 456
Bulk Delete Cutoff: 2026-08-04T19:30:45.123456+00:00

======================================================================

Channels Archived:

  #admiral
    Channel ID: 1538476446157115442
    Messages: 150

  #architect
    Channel ID: 1538767137080877056
    Messages: 200

  ...
```

---

## Discord API Limitations

### Bulk Delete Restrictions

- **14-day limit:** Discord only allows bulk deletion of messages < 14 days old
- **100 messages per call:** Maximum 100 messages can be deleted per API call
- **Rate limits:** 5 deletes per 5 seconds per channel (script handles this)

### Messages Older Than 14 Days

Messages older than 14 days:
- **Are archived** (included in JSON)
- **Cannot be bulk deleted** (Discord API restriction)
- Must be deleted individually (1 request per message, very slow)

---

## Execution Time Estimates

Typical execution times:

| Operation | Messages | Estimated Time |
|-----------|----------|----------------|
| Archive only | 1,000 msgs | 1-2 minutes |
| Archive only | 5,000 msgs | 5-10 minutes |
| Archive + Delete | 1,000 msgs (< 14 days) | 2-3 minutes |
| Archive + Delete | 5,000 msgs (< 14 days) | 10-15 minutes |

---

## Safety Features

1. **Archive-First Policy**
   - Always archives before deleting
   - Ensures no data loss

2. **3-Second Countdown**
   - Gives you time to cancel (Ctrl+C) before deletion starts

3. **Progress Tracking**
   - Shows real-time progress for each channel

4. **Error Handling**
   - Continues if a channel fails
   - Reports errors but doesn't stop execution

5. **Permissions Check**
   - Skips channels where bot lacks permissions

---

## Verification

After running the script:

### Check Archive Files

```bash
ls -lh /opt/Project-Tango/archives/discord_messages/
```

### View Summary

```bash
cat /opt/Project-Tango/archives/discord_messages/archive_summary_TIMESTAMP.txt
```

### Verify Message Count

```bash
# Count messages in JSON archive
jq '.total_messages' /opt/Project-Tango/archives/discord_messages/discord_archive_TIMESTAMP.json
```

---

## Troubleshooting

### "No permission to read/delete messages"

**Cause:** Bot lacks required permissions in channel  
**Solution:** Check bot role permissions in Discord server settings

### "Could not find channel"

**Cause:** Channel ID not configured or incorrect  
**Solution:** Verify channel IDs in `/opt/Project-Tango/.env`

### "Rate limit exceeded"

**Cause:** Too many API requests too quickly  
**Solution:** Script auto-handles rate limits with delays

---

## Restoration (If Needed)

To reference archived messages:

```bash
# Pretty-print entire archive
jq '.' /opt/Project-Tango/archives/discord_messages/discord_archive_TIMESTAMP.json | less

# View messages from specific channel
jq '.channels.admiral.messages' /opt/Project-Tango/archives/discord_messages/discord_archive_TIMESTAMP.json

# Search for specific content
jq '.channels[].messages[] | select(.content | contains("keyword"))' /opt/Project-Tango/archives/discord_messages/discord_archive_TIMESTAMP.json
```

---

## Security Notes

- Archive files contain **full message content** including user IDs and Discord IDs
- Store archives securely (they're already in `/opt/Project-Tango/archives/`)
- Do not commit archives to git (should be in `.gitignore`)
- Bot token (`SCHUBERT_BOT_TOKEN`) grants full message access

---

## Files Created

| File | Description | Location |
|------|-------------|----------|
| `discord_archive_TIMESTAMP.json` | Full message archive (JSON) | `/opt/Project-Tango/archives/discord_messages/` |
| `archive_summary_TIMESTAMP.txt` | Human-readable summary | `/opt/Project-Tango/archives/discord_messages/` |

---

## Next Steps After Running

1. **Verify archive was created**
   ```bash
   ls -lh /opt/Project-Tango/archives/discord_messages/
   ```

2. **Check summary report**
   ```bash
   cat /opt/Project-Tango/archives/discord_messages/archive_summary_*.txt
   ```

3. **Verify channels are clean** (if deletion was run)
   - Visit Discord channels in web/desktop app
   - Confirm test messages are gone

4. **Backup archive to external storage** (optional)
   ```bash
   # Example: Copy to external drive
   cp -r /opt/Project-Tango/archives/discord_messages/ /mnt/backup/
   ```

---

**END OF DOCUMENTATION**

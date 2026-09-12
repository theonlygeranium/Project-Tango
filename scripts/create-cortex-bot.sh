#!/bin/bash
# Create Dr. Cortex bot script from schubert-bot-v2.py template

set -e

SOURCE="/opt/Project-Tango/scripts/schubert-bot-v2.py"
TARGET="/opt/Project-Tango/scripts/dr-cortex-bot.py"

# Copy the source file
cp "$SOURCE" "$TARGET"

# Replace SCHUBERT_BOT_TOKEN with CORTEX_BOT_TOKEN
sed -i 's/SCHUBERT_BOT_TOKEN/CORTEX_BOT_TOKEN/g' "$TARGET"

# Replace SCHUBERT_BOT_ADMIN_USER_ID with CORTEX_BOT_ADMIN_USER_ID (but keep fallback to SCHUBERT)
sed -i 's/CORTEX_BOT_ADMIN_USER_ID/SCHUBERT_BOT_ADMIN_USER_ID/g' "$TARGET"

# Replace SCHUBERT_BOT_CHANNEL_ID with CORTEX_CHANNEL_ID
sed -i 's/SCHUBERT_BOT_CHANNEL_ID/CORTEX_CHANNEL_ID/g' "$TARGET"

# Replace log file
sed -i 's|/var/log/schubert-bot.log|/var/log/dr-cortex-bot.log|g' "$TARGET"

# Replace bot description in header
sed -i 's/Schubert Bot V2/Dr. Cortex Bot/g' "$TARGET"
sed -i 's/Admiral Schubert Maine Coon cat persona/Dr. Cortex alien scientist persona/g' "$TARGET"

# Make executable
chmod +x "$TARGET"

echo "✅ Dr. Cortex bot script created at $TARGET"

#!/bin/bash

# Asbestos Vision-CLI Bridge
# Connects to the running Asbestos Agent server to perform vision analysis

AGENT_URL="http://127.0.0.1:8765/v1/chat/completions"

# Usage check
if [ -z "$1" ]; then
    echo "Usage: ./vision.sh <path_to_image> [prompt]"
    echo "Example: ./vision.sh sample.jpg 'What is this image of?'"
    exit 1
fi

IMAGE_PATH="$1"
PROMPT="${2:-"Describe this image in detail."}"

if [ ! -f "$IMAGE_PATH" ]; then
    echo "Error: Image file not found at $IMAGE_PATH"
    exit 1
fi

echo "--- Asbestos Vision Analysis (Server Mode) ---"
echo "Image: $IMAGE_PATH"
echo "Prompt: $PROMPT"
echo "----------------------------------------------"

# Resize image down to max 1024px to prevent large model OOM/400 errors
TMP_IMG="/tmp/asbestos_vision_tmp.jpg"
sips -Z 1024 -s format jpeg "$IMAGE_PATH" --out "$TMP_IMG" >/dev/null 2>&1

MIMETYPE="image/jpeg"
BASE64_DATA=$(base64 -i "$TMP_IMG")

# Create JSON payload using jq to safely escape the prompt string
JSON_PAYLOAD=$(jq -n \
  --arg p "$PROMPT" \
  --arg b "data:$MIMETYPE;base64,$BASE64_DATA" \
'{
  "model": "asbestos-local",
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "text", "text": $p },
        { "type": "image_url", "image_url": { "url": $b } }
      ]
    }
  ]
}')

# Send to running server
curl -s -X POST $AGENT_URL \
     -H "Content-Type: application/json" \
     -d "$JSON_PAYLOAD" | python3 -c '
import sys, json

try:
    resp = json.load(sys.stdin)
    if "choices" in resp and len(resp["choices"]) > 0:
        print("\nAgent Response:")
        print(resp["choices"][0]["message"]["content"])
    else:
        print("\nError from server:")
        print(json.dumps(resp, indent=2))
except Exception as e:
    print("\nFailed to parse JSON response.")
'

# Cleanup
rm -f "$TMP_IMG"

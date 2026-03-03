#!/bin/bash

# Asbestos Vision-CLI Bridge
# A helper script to run Multimodal Vision analysis using llama-cli

# Configuration - update these paths as needed or link models to this folder
MODEL_NAME="Qwen_Qwen3.5-0.8B-Q8_0.gguf"
MMPROJ_NAME="mmproj-Qwen_Qwen3.5-0.8B-bf16.gguf"
CLI_BIN="../llama.cpp/bin/llama-cli"

# Look for models in the current dir, parent, or a 'models' folder
if [ -f "$MODEL_NAME" ]; then
    MODEL_PATH="$MODEL_NAME"
elif [ -f "../$MODEL_NAME" ]; then
    MODEL_PATH="../$MODEL_NAME"
elif [ -f "../models/$MODEL_NAME" ]; then
    MODEL_PATH="../models/$MODEL_NAME"
else
    echo "Error: Base model $MODEL_NAME not found."
    exit 1
fi

if [ -f "$MMPROJ_NAME" ]; then
    MMPROJ_PATH="$MMPROJ_NAME"
elif [ -f "../$MMPROJ_NAME" ]; then
    MMPROJ_PATH="../$MMPROJ_NAME"
elif [ -f "../models/$MMPROJ_NAME" ]; then
    MMPROJ_PATH="../models/$MMPROJ_NAME"
else
    echo "Error: Vision Projector $MMPROJ_NAME not found."
    exit 1
fi

if [ ! -f "$CLI_BIN" ]; then
    echo "Error: llama-cli binary not found at $CLI_BIN"
    exit 1
fi

# Usage check
if [ -z "$1" ]; then
    echo "Usage: ./vision.sh <path_to_image> [prompt]"
    echo "Example: ./vision.sh sample_vision.png 'Analyze this image.'"
    exit 1
fi

IMAGE_PATH="$1"
PROMPT="${2:-"Describe this image in detail."}"

echo "--- Asbestos Vision Analysis ---"
echo "Model: $MODEL_PATH"
echo "Image: $IMAGE_PATH"
echo "--------------------------------"

$CLI_BIN -m "$MODEL_PATH" \
         --mmproj "$MMPROJ_PATH" \
         --image "$IMAGE_PATH" \
         -p "$PROMPT" \
         -n 128

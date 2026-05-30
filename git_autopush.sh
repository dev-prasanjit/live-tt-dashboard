#!/bin/bash

# Navigate to the project directory
cd /Users/prasanjitdatta/Desktop/antigravity/tradetron_dashboard

# Check if a remote "origin" is configured
if ! git remote | grep -q "origin"; then
    echo "[$(date)] Error: No remote named 'origin' configured. Skipping auto-push."
    echo "Please add your GitHub repository remote using: git remote add origin <GitHub URL>"
    exit 0
fi

# Check if there are any changes (modified, untracked, deleted files)
if [ -n "$(git status --porcelain)" ]; then
    echo "[$(date)] Changes detected. Staging and committing..."
    git add -A
    git commit -m "Auto-update: $(date)"
    
    echo "[$(date)] Pushing changes to remote..."
    # Push to current branch (defaults to main)
    BRANCH=$(git branch --show-current)
    git push origin "$BRANCH" 2>&1
    
    if [ $? -eq 0 ]; then
        echo "[$(date)] Success: Push completed successfully."
    else
        echo "[$(date)] Error: Push failed. Make sure SSH authentication or credentials are configured."
    fi
else
    echo "[$(date)] No changes detected."
fi

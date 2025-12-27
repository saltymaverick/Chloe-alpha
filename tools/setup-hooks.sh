#!/bin/bash
# Chloe Alpha Development Setup Script
# Run this after cloning to enable security hooks

echo "🔧 Setting up Chloe Alpha development environment..."

# Configure git hooks path for security checks
if [ -d "tools/git-hooks" ]; then
    git config core.hooksPath tools/git-hooks
    echo "✅ Git hooks configured (security checks enabled)"
else
    echo "⚠️  Warning: tools/git-hooks not found"
fi

# Create .env from template if it doesn't exist
if [ ! -f ".env" ] && [ -f ".env_template.real" ]; then
    cp .env_template.real .env
    echo "✅ Created .env from template (add your API keys)"
else
    echo "ℹ️  .env already exists or template not found"
fi

echo ""
echo "🎯 Setup complete!"
echo "• Security hooks: ACTIVE"
echo "• Edit .env with your API credentials"
echo "• Run: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"

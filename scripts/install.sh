#!/bin/bash
#
# TapoCam Installation Script
# Installs TapoCam as a systemd service
#
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
INSTALL_DIR="/opt/tapocam"
CONFIG_DIR="/etc/tapocam"
DATA_DIR="/var/lib/tapocam"
SERVICE_USER="tapocam"
SERVICE_GROUP="tapocam"
SERVICE_NAME="tapocam"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${GREEN}=== TapoCam Installation ===${NC}"
echo

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
    exit 1
fi

# Check for uv or pip
if command -v uv &> /dev/null; then
    PKG_MANAGER="uv"
    echo -e "${GREEN}Using uv for package management${NC}"
elif command -v pip3 &> /dev/null; then
    PKG_MANAGER="pip"
    echo -e "${YELLOW}Using pip for package management (uv recommended)${NC}"
else
    echo -e "${RED}Error: Neither uv nor pip3 found. Please install uv or pip first.${NC}"
    exit 1
fi

# Create service user if doesn't exist
if ! id "$SERVICE_USER" &>/dev/null; then
    echo "Creating service user: $SERVICE_USER"
    useradd --system --no-create-home --shell /bin/false "$SERVICE_USER"
fi

# Create directories
echo "Creating directories..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$DATA_DIR"

# Copy project files
echo "Copying project files to $INSTALL_DIR..."
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='.git' \
    --exclude='*.pyc' --exclude='.env' --exclude='test_output' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

# Create virtual environment and install
echo "Setting up Python virtual environment..."
cd "$INSTALL_DIR"

if [[ "$PKG_MANAGER" == "uv" ]]; then
    uv venv .venv
    uv pip install -e ".[all]"
else
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -e ".[all]"
fi

# Copy example config if no config exists
if [[ ! -f "$CONFIG_DIR/config.yaml" ]]; then
    echo "Installing example configuration..."
    cp "$INSTALL_DIR/config.example.yaml" "$CONFIG_DIR/config.yaml"
    echo -e "${YELLOW}Please edit $CONFIG_DIR/config.yaml with your camera settings${NC}"
fi

# Create environment file for secrets
if [[ ! -f "$CONFIG_DIR/environment" ]]; then
    echo "Creating environment file..."
    cat > "$CONFIG_DIR/environment" << 'EOF'
# TapoCam Environment Variables
# Add your RTSP URLs and API keys here
# Example:
# CAM01_RTSP_URL=rtsp://user:pass@192.168.1.100:554/stream1
# API_TOKEN=your-api-token-here
EOF
    chmod 600 "$CONFIG_DIR/environment"
fi

# Set permissions
echo "Setting permissions..."
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$DATA_DIR"
chown -R root:$SERVICE_GROUP "$CONFIG_DIR"
chmod 750 "$CONFIG_DIR"
chmod 640 "$CONFIG_DIR/config.yaml"
chmod 600 "$CONFIG_DIR/environment"

# Install systemd service
echo "Installing systemd service..."
cp "$INSTALL_DIR/scripts/tapocam.service" /etc/systemd/system/
systemctl daemon-reload

# Enable service (but don't start yet)
systemctl enable "$SERVICE_NAME"

echo
echo -e "${GREEN}=== Installation Complete ===${NC}"
echo
echo "Next steps:"
echo "  1. Edit configuration:  sudo nano $CONFIG_DIR/config.yaml"
echo "  2. Set environment vars: sudo nano $CONFIG_DIR/environment"
echo "  3. Start service:        sudo systemctl start $SERVICE_NAME"
echo "  4. Check status:         sudo systemctl status $SERVICE_NAME"
echo "  5. View logs:            sudo journalctl -u $SERVICE_NAME -f"
echo
echo "Web dashboard will be available at: http://localhost:8000/"
echo

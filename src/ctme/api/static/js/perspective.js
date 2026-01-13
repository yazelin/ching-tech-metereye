/**
 * Perspective Selector - Canvas-based 4-point perspective selection
 * With zoom and pan support for precise point placement
 */
class PerspectiveSelector {
    constructor(canvas, options = {}) {
        this.canvas = canvas;
        this.ctx = canvas.getContext('2d');
        this.points = [];
        this.draggingPoint = null;
        this.image = null;

        // Zoom and pan state
        this.scale = 1;
        this.minScale = 0.5;
        this.maxScale = 5;
        this.offsetX = 0;
        this.offsetY = 0;
        this.isPanning = false;
        this.lastPanX = 0;
        this.lastPanY = 0;

        // Display dimensions (set in _setupCanvas)
        this.displayWidth = canvas.width;
        this.displayHeight = canvas.height;

        // Options
        this.onPointsChange = options.onPointsChange || (() => {});
        this.pointRadius = options.pointRadius || 12;
        this.lineWidth = options.lineWidth || 2;

        // Colors for each point (TL, TR, BR, BL)
        this.pointColors = ['#ef4444', '#22c55e', '#3b82f6', '#eab308'];
        this.pointLabels = ['TL', 'TR', 'BR', 'BL'];

        // Bind event handlers
        this._onMouseDown = this._onMouseDown.bind(this);
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onWheel = this._onWheel.bind(this);
        this._onTouchStart = this._onTouchStart.bind(this);
        this._onTouchMove = this._onTouchMove.bind(this);
        this._onTouchEnd = this._onTouchEnd.bind(this);
        this._onContextMenu = this._onContextMenu.bind(this);

        this._attachEvents();
    }

    _attachEvents() {
        this.canvas.addEventListener('mousedown', this._onMouseDown);
        this.canvas.addEventListener('mousemove', this._onMouseMove);
        this.canvas.addEventListener('mouseup', this._onMouseUp);
        this.canvas.addEventListener('mouseleave', this._onMouseUp);
        this.canvas.addEventListener('wheel', this._onWheel, { passive: false });
        this.canvas.addEventListener('touchstart', this._onTouchStart, { passive: false });
        this.canvas.addEventListener('touchmove', this._onTouchMove, { passive: false });
        this.canvas.addEventListener('touchend', this._onTouchEnd);
        this.canvas.addEventListener('contextmenu', this._onContextMenu);
    }

    destroy() {
        this.canvas.removeEventListener('mousedown', this._onMouseDown);
        this.canvas.removeEventListener('mousemove', this._onMouseMove);
        this.canvas.removeEventListener('mouseup', this._onMouseUp);
        this.canvas.removeEventListener('mouseleave', this._onMouseUp);
        this.canvas.removeEventListener('wheel', this._onWheel);
        this.canvas.removeEventListener('touchstart', this._onTouchStart);
        this.canvas.removeEventListener('touchmove', this._onTouchMove);
        this.canvas.removeEventListener('touchend', this._onTouchEnd);
        this.canvas.removeEventListener('contextmenu', this._onContextMenu);
    }

    // Convert screen coordinates to display coordinates (not DPR-scaled)
    _screenToCanvas(screenX, screenY) {
        const rect = this.canvas.getBoundingClientRect();
        // Return display coordinates, not internal canvas coordinates
        const x = (screenX - rect.left) / rect.width * this.displayWidth;
        const y = (screenY - rect.top) / rect.height * this.displayHeight;
        return { x, y };
    }

    // Convert canvas coordinates to image coordinates (accounting for zoom/pan)
    _canvasToImage(canvasX, canvasY) {
        return {
            x: (canvasX - this.offsetX) / this.scale,
            y: (canvasY - this.offsetY) / this.scale
        };
    }

    // Convert image coordinates to canvas coordinates
    _imageToCanvas(imageX, imageY) {
        return {
            x: imageX * this.scale + this.offsetX,
            y: imageY * this.scale + this.offsetY
        };
    }

    // Get image coordinates from mouse event
    _getImageCoords(e) {
        const screen = this._screenToCanvas(e.clientX, e.clientY);
        return this._canvasToImage(screen.x, screen.y);
    }

    _findPointAtPosition(imageX, imageY) {
        // Hit radius in image space - larger when zoomed out for easier grabbing
        // pointRadius is in display space, so convert to image space and add margin
        const hitRadius = (this.pointRadius + 10) / this.scale;
        for (let i = 0; i < this.points.length; i++) {
            const p = this.points[i];
            const dx = imageX - p.x;
            const dy = imageY - p.y;
            if (dx * dx + dy * dy < hitRadius * hitRadius) {
                return i;
            }
        }
        return -1;
    }

    _onMouseDown(e) {
        const imageCoords = this._getImageCoords(e);

        // Middle mouse button or Ctrl+Left click for panning
        if (e.button === 1 || (e.button === 0 && e.ctrlKey)) {
            e.preventDefault();
            this.isPanning = true;
            this.lastPanX = e.clientX;
            this.lastPanY = e.clientY;
            this.canvas.style.cursor = 'grabbing';
            return;
        }

        // Right click handled by context menu
        if (e.button === 2) return;

        this._handlePointerDown(imageCoords);
    }

    _onMouseMove(e) {
        if (this.isPanning) {
            const dx = e.clientX - this.lastPanX;
            const dy = e.clientY - this.lastPanY;

            // Scale movement to display space
            const rect = this.canvas.getBoundingClientRect();
            this.offsetX += dx / rect.width * this.displayWidth;
            this.offsetY += dy / rect.height * this.displayHeight;

            this.lastPanX = e.clientX;
            this.lastPanY = e.clientY;
            this.render();
            return;
        }

        const imageCoords = this._getImageCoords(e);
        this._handlePointerMove(imageCoords);
    }

    _onMouseUp(e) {
        if (this.isPanning) {
            this.isPanning = false;
            this.canvas.style.cursor = 'crosshair';
            return;
        }
        this._handlePointerUp();
    }

    _onWheel(e) {
        e.preventDefault();

        const rect = this.canvas.getBoundingClientRect();
        const mouseX = (e.clientX - rect.left) / rect.width * this.displayWidth;
        const mouseY = (e.clientY - rect.top) / rect.height * this.displayHeight;

        // Zoom centered on mouse position
        const zoom = e.deltaY < 0 ? 1.15 : 0.87;
        const newScale = Math.min(this.maxScale, Math.max(this.minScale, this.scale * zoom));

        if (newScale !== this.scale) {
            // Adjust offset to zoom toward mouse position
            const scaleDiff = newScale / this.scale;
            this.offsetX = mouseX - (mouseX - this.offsetX) * scaleDiff;
            this.offsetY = mouseY - (mouseY - this.offsetY) * scaleDiff;
            this.scale = newScale;
            this.render();

            // Update zoom display
            if (this.onZoomChange) {
                this.onZoomChange(this.scale);
            }
        }
    }

    _onTouchStart(e) {
        e.preventDefault();

        if (e.touches.length === 2) {
            // Pinch zoom start
            this._lastPinchDist = this._getPinchDistance(e);
            this._lastPinchCenter = this._getPinchCenter(e);
            return;
        }

        const touch = e.touches[0];
        const screen = this._screenToCanvas(touch.clientX, touch.clientY);
        const imageCoords = this._canvasToImage(screen.x, screen.y);

        this._handlePointerDown(imageCoords);

        // Long press for delete
        this._longPressTimer = setTimeout(() => {
            const pointIndex = this._findPointAtPosition(imageCoords.x, imageCoords.y);
            if (pointIndex >= 0) {
                this._removePoint(pointIndex);
            }
        }, 500);
    }

    _onTouchMove(e) {
        e.preventDefault();
        clearTimeout(this._longPressTimer);

        if (e.touches.length === 2) {
            // Pinch zoom
            const dist = this._getPinchDistance(e);
            const center = this._getPinchCenter(e);

            const zoom = dist / this._lastPinchDist;
            const newScale = Math.min(this.maxScale, Math.max(this.minScale, this.scale * zoom));

            if (newScale !== this.scale) {
                const scaleDiff = newScale / this.scale;
                this.offsetX = center.x - (center.x - this.offsetX) * scaleDiff;
                this.offsetY = center.y - (center.y - this.offsetY) * scaleDiff;
                this.scale = newScale;
            }

            // Pan with pinch center movement
            this.offsetX += center.x - this._lastPinchCenter.x;
            this.offsetY += center.y - this._lastPinchCenter.y;

            this._lastPinchDist = dist;
            this._lastPinchCenter = center;
            this.render();
            return;
        }

        const touch = e.touches[0];
        const screen = this._screenToCanvas(touch.clientX, touch.clientY);
        const imageCoords = this._canvasToImage(screen.x, screen.y);
        this._handlePointerMove(imageCoords);
    }

    _onTouchEnd(e) {
        clearTimeout(this._longPressTimer);
        this._handlePointerUp();
    }

    _getPinchDistance(e) {
        const dx = e.touches[0].clientX - e.touches[1].clientX;
        const dy = e.touches[0].clientY - e.touches[1].clientY;
        return Math.sqrt(dx * dx + dy * dy);
    }

    _getPinchCenter(e) {
        const rect = this.canvas.getBoundingClientRect();
        return {
            x: ((e.touches[0].clientX + e.touches[1].clientX) / 2 - rect.left) / rect.width * this.displayWidth,
            y: ((e.touches[0].clientY + e.touches[1].clientY) / 2 - rect.top) / rect.height * this.displayHeight
        };
    }

    _onContextMenu(e) {
        e.preventDefault();
        const imageCoords = this._getImageCoords(e);
        const pointIndex = this._findPointAtPosition(imageCoords.x, imageCoords.y);
        if (pointIndex >= 0) {
            this._removePoint(pointIndex);
        }
    }

    _handlePointerDown(imageCoords) {
        const pointIndex = this._findPointAtPosition(imageCoords.x, imageCoords.y);

        if (pointIndex >= 0) {
            // Start dragging existing point
            this.draggingPoint = pointIndex;
            this.canvas.style.cursor = 'grabbing';
        } else if (this.points.length < 4) {
            // Add new point (constrain to image bounds)
            const x = Math.max(0, Math.min(this.image?.width || this.canvas.width, imageCoords.x));
            const y = Math.max(0, Math.min(this.image?.height || this.canvas.height, imageCoords.y));
            this.points.push({ x, y });
            this.render();
            this._notifyChange();
        }
    }

    _handlePointerMove(imageCoords) {
        if (this.draggingPoint !== null) {
            // Constrain to image bounds
            const maxX = this.image?.width || this.canvas.width;
            const maxY = this.image?.height || this.canvas.height;
            const x = Math.max(0, Math.min(maxX, imageCoords.x));
            const y = Math.max(0, Math.min(maxY, imageCoords.y));

            this.points[this.draggingPoint] = { x, y };
            this.render();
            this._notifyChange();
        } else {
            // Update cursor based on hover
            const pointIndex = this._findPointAtPosition(imageCoords.x, imageCoords.y);
            this.canvas.style.cursor = pointIndex >= 0 ? 'grab' : 'crosshair';
        }
    }

    _handlePointerUp() {
        this.draggingPoint = null;
        this.canvas.style.cursor = 'crosshair';
    }

    _removePoint(index) {
        if (index >= 0 && index < this.points.length) {
            this.points.splice(index, 1);
            this.render();
            this._notifyChange();
        }
    }

    _notifyChange() {
        if (this.points.length === 4) {
            const ordered = this._orderPoints();
            this.onPointsChange(ordered);
        } else {
            this.onPointsChange(null);
        }
    }

    _orderPoints() {
        if (this.points.length !== 4) return null;

        // Sort by Y coordinate
        const sorted = [...this.points].sort((a, b) => a.y - b.y);

        // Top two points
        const topPoints = sorted.slice(0, 2).sort((a, b) => a.x - b.x);
        // Bottom two points
        const bottomPoints = sorted.slice(2, 4).sort((a, b) => a.x - b.x);

        // Order: TL, TR, BR, BL
        return [
            topPoints[0],
            topPoints[1],
            bottomPoints[1],
            bottomPoints[0]
        ];
    }

    setImage(imageUrl) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = () => {
                this.image = img;
                this._setupCanvas();
                this.resetView();
                this.render();
                resolve();
            };
            img.onerror = reject;
            img.src = imageUrl;
        });
    }

    _setupCanvas() {
        if (!this.image) return;

        // Set canvas to match container, but maintain reasonable resolution
        const container = this.canvas.parentElement;
        const containerWidth = container.clientWidth;
        const containerHeight = Math.min(700, window.innerHeight * 0.7);

        // Canvas display size
        this.canvas.style.width = containerWidth + 'px';
        this.canvas.style.height = containerHeight + 'px';

        // Canvas internal resolution (higher for quality)
        const dpr = window.devicePixelRatio || 1;
        this.canvas.width = containerWidth * dpr;
        this.canvas.height = containerHeight * dpr;

        // Scale context for high DPI
        this.ctx.scale(dpr, dpr);
        this.displayWidth = containerWidth;
        this.displayHeight = containerHeight;
    }

    resetView() {
        if (!this.image) return;

        // Fit image to canvas with some padding
        const padding = 20;
        const availWidth = this.displayWidth - padding * 2;
        const availHeight = this.displayHeight - padding * 2;

        const scaleX = availWidth / this.image.width;
        const scaleY = availHeight / this.image.height;
        this.scale = Math.min(scaleX, scaleY, 1); // Don't scale up beyond 100%

        // Center image
        this.offsetX = (this.displayWidth - this.image.width * this.scale) / 2;
        this.offsetY = (this.displayHeight - this.image.height * this.scale) / 2;

        this.render();

        if (this.onZoomChange) {
            this.onZoomChange(this.scale);
        }
    }

    setZoom(scale) {
        const centerX = this.displayWidth / 2;
        const centerY = this.displayHeight / 2;

        const newScale = Math.min(this.maxScale, Math.max(this.minScale, scale));
        const scaleDiff = newScale / this.scale;

        this.offsetX = centerX - (centerX - this.offsetX) * scaleDiff;
        this.offsetY = centerY - (centerY - this.offsetY) * scaleDiff;
        this.scale = newScale;

        this.render();
    }

    setPoints(points) {
        if (points && points.length === 4) {
            this.points = points.map(p => ({ x: p[0], y: p[1] }));
        } else {
            this.points = [];
        }
        this.render();
    }

    getPoints() {
        if (this.points.length !== 4) return null;
        const ordered = this._orderPoints();
        return ordered.map(p => [Math.round(p.x), Math.round(p.y)]);
    }

    reset() {
        this.points = [];
        this.render();
        this._notifyChange();
    }

    render() {
        const ctx = this.ctx;
        const dpr = window.devicePixelRatio || 1;

        // Clear with dark background
        ctx.fillStyle = '#1a1a2e';
        ctx.fillRect(0, 0, this.displayWidth, this.displayHeight);

        // Draw image with current transform
        if (this.image) {
            ctx.save();
            ctx.translate(this.offsetX, this.offsetY);
            ctx.scale(this.scale, this.scale);
            ctx.drawImage(this.image, 0, 0);
            ctx.restore();
        }

        // Draw polygon if 4 points
        if (this.points.length === 4) {
            const ordered = this._orderPoints();
            const canvasPoints = ordered.map(p => this._imageToCanvas(p.x, p.y));

            // Fill
            ctx.beginPath();
            ctx.moveTo(canvasPoints[0].x, canvasPoints[0].y);
            for (let i = 1; i < 4; i++) {
                ctx.lineTo(canvasPoints[i].x, canvasPoints[i].y);
            }
            ctx.closePath();
            ctx.fillStyle = 'rgba(59, 130, 246, 0.2)';
            ctx.fill();

            // Stroke
            ctx.strokeStyle = '#3b82f6';
            ctx.lineWidth = this.lineWidth;
            ctx.stroke();
        } else if (this.points.length > 1) {
            // Draw lines between points
            const canvasPoints = this.points.map(p => this._imageToCanvas(p.x, p.y));
            ctx.beginPath();
            ctx.moveTo(canvasPoints[0].x, canvasPoints[0].y);
            for (let i = 1; i < canvasPoints.length; i++) {
                ctx.lineTo(canvasPoints[i].x, canvasPoints[i].y);
            }
            ctx.strokeStyle = '#3b82f6';
            ctx.lineWidth = this.lineWidth;
            ctx.stroke();
        }

        // Draw points
        const ordered = this.points.length === 4 ? this._orderPoints() : this.points;
        for (let i = 0; i < ordered.length; i++) {
            const p = ordered[i];
            const canvasP = this._imageToCanvas(p.x, p.y);
            const color = this.pointColors[i] || '#ffffff';
            const radius = this.pointRadius;

            // Outer circle (white border)
            ctx.beginPath();
            ctx.arc(canvasP.x, canvasP.y, radius + 3, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.fill();

            // Inner circle (colored)
            ctx.beginPath();
            ctx.arc(canvasP.x, canvasP.y, radius, 0, Math.PI * 2);
            ctx.fillStyle = color;
            ctx.fill();

            // Label
            ctx.font = 'bold 11px sans-serif';
            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            if (this.points.length === 4) {
                ctx.fillText(this.pointLabels[i], canvasP.x, canvasP.y);
            } else {
                ctx.fillText((i + 1).toString(), canvasP.x, canvasP.y);
            }
        }

        // Draw instructions and zoom info
        this._drawOverlay();
    }

    _drawOverlay() {
        const ctx = this.ctx;

        // Zoom indicator (top-left)
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        ctx.fillRect(8, 8, 70, 24);
        ctx.fillStyle = '#ffffff';
        ctx.font = '12px sans-serif';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(`${Math.round(this.scale * 100)}%`, 16, 20);

        // Instructions (bottom)
        if (this.points.length < 4) {
            const remaining = 4 - this.points.length;
            const text = `Click to add ${remaining} more point${remaining > 1 ? 's' : ''}`;

            ctx.fillStyle = 'rgba(0, 0, 0, 0.7)';
            const metrics = ctx.measureText(text);
            const boxWidth = metrics.width + 24;
            ctx.fillRect((this.displayWidth - boxWidth) / 2, this.displayHeight - 36, boxWidth, 28);

            ctx.fillStyle = '#ffffff';
            ctx.textAlign = 'center';
            ctx.fillText(text, this.displayWidth / 2, this.displayHeight - 22);
        }

        // Controls hint (bottom-right)
        ctx.fillStyle = 'rgba(0, 0, 0, 0.6)';
        ctx.fillRect(this.displayWidth - 200, this.displayHeight - 36, 192, 28);
        ctx.fillStyle = '#9ca3af';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText('Scroll: Zoom | Ctrl+Drag: Pan', this.displayWidth - 16, this.displayHeight - 22);
    }
}

// Export for use in other modules
window.PerspectiveSelector = PerspectiveSelector;

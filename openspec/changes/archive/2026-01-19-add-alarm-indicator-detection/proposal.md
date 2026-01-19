# Change: 新增警報燈偵測功能

## Why
工廠現場除了數位儀表外，還有許多警報指示燈（如火災警報、設備異常燈號）需要監控。目前系統只能辨識七段顯示器的數值，無法偵測燈號的開/關狀態。新增此功能可讓用戶透過同一套系統同時監控儀表數值與警報狀態。

## What Changes
- 新增 `Indicator` 資料模型，類似 `Meter` 但輸出為布林值（on/off）
- 新增 `IndicatorDetector` 類別，分析 ROI 區域的亮度/顏色判斷燈號狀態
- 擴充 `CameraConfigData` 支援 `indicators` 設定（與 `meters` 並列）
- 擴充 `Reading` 模型支援二進位狀態記錄
- 擴充 Dashboard 與 API 顯示燈號狀態
- 資料庫 schema 支援儲存燈號狀態歷史

## Impact
- Affected specs: `alarm-detection` (新增)
- Affected code:
  - `src/ctme/models.py` - 新增 IndicatorConfigData, IndicatorStatus
  - `src/ctme/indicator.py` - 新增燈號偵測邏輯
  - `src/ctme/camera_manager.py` - 處理 indicator 偵測
  - `src/ctme/config_yaml.py` - 解析 indicators 設定
  - `src/ctme/api/` - 新增 indicator 相關 API
  - `src/ctme/export/database.py` - 擴充資料表

## Config 範例
```yaml
cameras:
  - id: cam-01
    name: "火災警報面板"
    url: "rtsp://..."
    meters: []  # 無數位儀表
    indicators:
      - id: fire-alarm-01
        name: "西側PBL"
        perspective:
          points: [[100, 50], [200, 100], [200, 150], [100, 150]]
          output_size: [100, 50]
        detection:
          mode: brightness  # brightness 或 color
          threshold: 128    # 亮度閾值 (0-255)
          on_color: red     # 選用：指定燈號顏色
        show_on_dashboard: true
```

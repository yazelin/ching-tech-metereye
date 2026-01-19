## ADDED Requirements

### Requirement: Indicator Configuration
系統 SHALL 支援在每個攝影機下設定多個指示燈 (Indicator)，每個指示燈有獨立的 ROI 設定與偵測參數。

#### Scenario: 設定單一指示燈
- **WHEN** 用戶在 config.yaml 新增一個 indicator 設定
- **THEN** 系統載入該 indicator 的 id, name, perspective points, detection 參數

#### Scenario: 同一攝影機設定多個指示燈
- **WHEN** 用戶在同一個 camera 下設定多個 indicators
- **THEN** 系統為每個 indicator 建立獨立的偵測器並分別處理

#### Scenario: 攝影機同時有 meters 和 indicators
- **WHEN** 攝影機設定同時包含 meters 和 indicators
- **THEN** 系統同時處理數值辨識與燈號偵測，結果分別記錄

### Requirement: Brightness Detection Mode
系統 SHALL 支援亮度偵測模式，透過分析 ROI 區域的平均亮度判斷燈號是否亮起。

#### Scenario: 燈號亮起（亮度高於閾值）
- **WHEN** ROI 區域平均亮度高於設定的 threshold
- **THEN** 系統判定燈號狀態為 ON (true/1)

#### Scenario: 燈號熄滅（亮度低於閾值）
- **WHEN** ROI 區域平均亮度低於設定的 threshold
- **THEN** 系統判定燈號狀態為 OFF (false/0)

#### Scenario: 自動閾值校正
- **WHEN** threshold 設定為 0
- **THEN** 系統使用 Otsu 演算法自動決定最佳閾值

### Requirement: Color Detection Mode
系統 SHALL 支援顏色偵測模式，透過分析 ROI 區域的特定顏色比例判斷燈號狀態。

#### Scenario: 偵測紅色警報燈
- **WHEN** detection mode 設為 color 且 on_color 設為 red
- **THEN** 系統分析 ROI 中紅色像素佔比，超過閾值判定為 ON

#### Scenario: 偵測綠色指示燈
- **WHEN** detection mode 設為 color 且 on_color 設為 green
- **THEN** 系統分析 ROI 中綠色像素佔比，超過閾值判定為 ON

### Requirement: Indicator Reading Export
系統 SHALL 將指示燈狀態與儀表讀數一起匯出至設定的目標（HTTP、MQTT、Database）。

#### Scenario: HTTP 匯出包含 indicator 狀態
- **WHEN** HTTP exporter 啟用且有 indicator reading
- **THEN** JSON payload 包含 indicator_id, state (boolean), timestamp

#### Scenario: Database 儲存 indicator 歷史
- **WHEN** Database exporter 啟用
- **THEN** indicator readings 儲存至 indicator_readings 資料表

#### Scenario: MQTT 發布 indicator 狀態
- **WHEN** MQTT exporter 啟用
- **THEN** indicator 狀態發布至 topic: `ctme/{camera_id}/{indicator_id}`

### Requirement: Indicator Dashboard Display
系統 SHALL 在 Web Dashboard 顯示所有 indicator 的即時狀態。

#### Scenario: 顯示燈號開啟狀態
- **WHEN** indicator 狀態為 ON
- **THEN** Dashboard 顯示該燈號為亮起狀態（紅色/綠色視覺指示）

#### Scenario: 顯示燈號關閉狀態
- **WHEN** indicator 狀態為 OFF
- **THEN** Dashboard 顯示該燈號為熄滅狀態（灰色視覺指示）

### Requirement: Indicator Configuration API
系統 SHALL 提供 REST API 管理 indicator 設定。

#### Scenario: 取得所有 indicators
- **WHEN** GET /api/indicators
- **THEN** 回傳所有 indicator 的設定與目前狀態

#### Scenario: 新增 indicator
- **WHEN** POST /api/cameras/{camera_id}/indicators 帶有 indicator 設定
- **THEN** 系統新增該 indicator 並開始偵測

#### Scenario: 更新 indicator 設定
- **WHEN** PATCH /api/indicators/{indicator_id} 帶有更新參數
- **THEN** 系統更新設定並套用新的偵測參數

#### Scenario: 刪除 indicator
- **WHEN** DELETE /api/indicators/{indicator_id}
- **THEN** 系統移除該 indicator 並停止偵測

### Requirement: Indicator Preview
系統 SHALL 提供 indicator 設定預覽功能，讓用戶在儲存前確認偵測效果。

#### Scenario: 預覽亮度偵測結果
- **WHEN** 用戶在設定頁面調整 indicator 參數並點擊預覽
- **THEN** 系統顯示 ROI 裁切結果、目前亮度值、判定狀態

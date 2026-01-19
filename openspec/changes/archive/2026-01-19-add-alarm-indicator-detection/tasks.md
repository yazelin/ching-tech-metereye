## 1. 資料模型
- [x] 1.1 新增 `IndicatorConfigData` dataclass（id, name, perspective, detection settings）
- [x] 1.2 新增 `IndicatorStatus` dataclass（狀態追蹤）
- [x] 1.3 擴充 `CameraConfigData` 加入 `indicators` 欄位
- [x] 1.4 新增 `IndicatorReading` 或擴充 `Reading` 支援布林值

## 2. 燈號偵測器
- [x] 2.1 新增 `src/ctme/indicator.py` 模組
- [x] 2.2 實作 `IndicatorDetector` 類別
- [x] 2.3 實作亮度偵測模式（brightness mode）
- [x] 2.4 實作顏色偵測模式（color mode）
- [x] 2.5 新增偵測結果視覺化（debug image）

## 3. 設定檔解析
- [x] 3.1 擴充 `config_yaml.py` 解析 `indicators` 設定
- [x] 3.2 新增 indicator config 驗證邏輯
- [x] 3.3 更新 `config.example.yaml` 加入範例

## 4. Camera Manager 整合
- [x] 4.1 擴充 `CameraManager` 處理 indicators
- [x] 4.2 在 frame processing 中加入 indicator 偵測
- [x] 4.3 發送 indicator reading 到 exporters

## 5. API 擴充
- [x] 5.1 新增 `/api/indicators` 端點
- [x] 5.2 新增 `/api/cameras/{id}/indicators` 端點
- [x] 5.3 擴充 config API 支援 indicator CRUD
- [x] 5.4 新增 `/api/preview/indicator` 端點

## 6. 前端 Dashboard
- [x] 6.1 擴充 index.html 顯示 indicator 狀態
- [x] 6.2 擴充 config.html 支援 indicator 設定
- [x] 6.3 新增 indicator 預覽功能

## 7. 資料匯出
- [x] 7.1 擴充 database schema 支援 indicator readings
- [x] 7.2 擴充 HTTP/MQTT exporter 發送 indicator 狀態

## 8. 文件
- [x] 8.1 更新 README.md 加入 indicator 功能說明
- [x] 8.2 新增 docs/database-setup.md 資料庫設定文件

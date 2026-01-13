# MeterEye

**ChingTech (擎添工業)** 開發的多攝影機儀表監控系統，用於讀取七段顯示器數值。

## 功能

- **多攝影機支援** - 同時監控多台 RTSP 攝影機
- **七段顯示器辨識** - 自動辨識 0-9 數字及小數點
- **多錶頭支援** - 單一畫面可監控多個壓力錶
- **4 點透視校正** - 網頁介面互動式校正傾斜角度
- **NVR 風格 Dashboard** - 分割畫面即時監控
- **Web 設定介面** - 瀏覽器上完成所有設定
- **數值正規化** - 支援小數點位數與單位設定
- **熱重載** - 修改設定無需重啟服務
- **REST API** - 遠端監控與整合

## 安裝

需要 Python 3.11+ 和 [uv](https://github.com/astral-sh/uv)。

```bash
# 安裝依賴
uv sync

# 執行
uv run ctme
```

## 使用方式

### 啟動服務

```bash
# 使用預設設定檔
uv run ctme

# 使用指定設定檔
uv run ctme --config /path/to/config.yaml
```

服務啟動後，開啟瀏覽器：
- **Dashboard**: http://localhost:8000
- **設定頁面**: http://localhost:8000/config.html

### Dashboard 操作

| 按鍵 | 功能 |
|------|------|
| `1`-`4` | 切換排版 (1x1, 2x2, 3x3, 4x4) |
| `F` | 全螢幕 |
| `ESC` | 退出全螢幕/返回 |
| 點擊攝影機 | 放大至 1x1 |

### Web 設定介面

透過 `/config.html` 可以：
- 新增/編輯/刪除攝影機
- 設定錶頭透視校正（4 點選取）
- 調整辨識參數（顏色通道、閾值、顯示模式）
- 設定預期位數、小數點位數、單位
- 即時預覽辨識結果

### 設定檔

YAML 格式設定檔位於 `~/.config/ctme/config.yaml`。

```yaml
cameras:
  - id: cam-01
    name: 壓力錶 1
    url: ${RTSP_URL_1}  # 支援環境變數
    enabled: true
    meters:
      - id: meter-01
        name: 主錶
        perspective:
          points: [[100, 50], [300, 50], [300, 150], [100, 150]]
          output_size: [400, 100]
        recognition:
          display_mode: light_on_dark
          color_channel: red
          threshold: 0  # 0 = Auto (Otsu)
        expected_digits: 3  # 預期位數 (0=自動)
        decimal_places: 2   # 小數點位數
        unit: "kPa"         # 單位
```

### 環境變數

建議使用環境變數管理 RTSP URL（避免密碼明碼）：

```bash
cp .env.example .env
# 編輯 .env 設定 RTSP_URL
uv run ctme
```

### 從舊版遷移

如果有舊版 JSON 設定檔，可以用遷移指令：

```bash
uv run ctme migrate
uv run ctme migrate --json /path/to/legacy.json
```

## 專案結構

```
ching-tech-metereye/
├── src/ctme/
│   ├── main.py           # 主程式入口
│   ├── runner.py         # 伺服器主程式
│   ├── camera_manager.py # 多攝影機管理
│   ├── config_yaml.py    # YAML 設定管理
│   ├── recognition.py    # 七段顯示器辨識
│   ├── models.py         # 資料模型
│   └── api/
│       ├── server.py      # FastAPI 服務
│       ├── config_routes.py # 設定 API
│       └── static/        # Web 前端
│           ├── index.html # Dashboard
│           ├── config.html # 設定頁面
│           └── css/       # 樣式
├── openspec/             # 規格文件與變更提案
└── pyproject.toml        # 專案設定
```

## REST API

| 端點 | 說明 |
|------|------|
| `GET /api/status` | 系統狀態 |
| `GET /api/cameras` | 攝影機列表 |
| `GET /api/cameras/{id}` | 攝影機詳細資訊 |
| `GET /api/readings` | 最新讀數 |
| `GET /stream/{id}` | MJPEG 串流 |
| `GET /snapshot/{id}` | 單張快照 |

設定 API：
| 端點 | 說明 |
|------|------|
| `GET /api/config/cameras` | 攝影機設定列表 |
| `POST /api/config/cameras` | 新增攝影機 |
| `PUT /api/config/cameras/{id}` | 更新攝影機 |
| `DELETE /api/config/cameras/{id}` | 刪除攝影機 |
| `POST /api/config/save` | 儲存設定至檔案 |
| `POST /api/config/reload` | 熱重載設定 |

## 授權

MIT License

---

**MeterEye** by **ChingTech (擎添工業)**

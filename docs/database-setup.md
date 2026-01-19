# 資料庫設定

MeterEye 支援將讀數匯出至 PostgreSQL 資料庫，方便後續查詢與分析。

## 使用 Docker Compose 部署

專案提供 Docker Compose 設定檔，可快速部署 PostgreSQL：

```bash
cd docker

# 複製環境變數範本
cp .env.example .env

# 編輯設定（務必修改密碼！）
nano .env

# 啟動資料庫
docker compose up -d

# 檢查狀態
docker compose ps
docker compose logs -f
```

## 環境變數說明

編輯 `docker/.env`：

```bash
# 資料庫對外 Port（預設 5433，避免與本機 PostgreSQL 衝突）
DB_PORT=5433

# 應用程式使用的帳號（MeterEye 寫入用）
DB_USER=metereye
DB_PASSWORD=請更換成安全的密碼
DB_NAME=metereye

# 唯讀帳號（給 Grafana、Metabase 等外部工具查詢用）
DB_READONLY_USER=metereye_reader
DB_READONLY_PASSWORD=請更換成安全的密碼
```

## MeterEye 設定

在 `config.yaml` 中設定連線字串：

```yaml
export:
  database:
    enabled: true
    type: postgresql
    connection_string: "postgresql+psycopg://metereye:你的密碼@localhost:5433/metereye"
    retention_days: 30
```

## 外部工具連線

提供唯讀帳號給 Grafana、Metabase 等工具：

| 設定項目 | 值 |
|---------|-----|
| Host | 伺服器 IP |
| Port | 5433（或你設定的 DB_PORT） |
| Database | metereye |
| User | metereye_reader |
| Password | 你設定的 DB_READONLY_PASSWORD |

此帳號僅有 SELECT 權限，無法修改或刪除資料。

## 資料表結構

### readings（儀表讀數）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 主鍵 |
| camera_id | VARCHAR(64) | 攝影機 ID |
| meter_id | VARCHAR(64) | 錶頭 ID |
| value | FLOAT | 讀數值（可能為 NULL） |
| raw_text | VARCHAR(32) | 原始辨識文字 |
| timestamp | DATETIME | 讀取時間 |
| confidence | FLOAT | 信心度（1.0=成功辨識，0.0=辨識失敗） |

### indicator_readings（指示燈讀數）

| 欄位 | 類型 | 說明 |
|------|------|------|
| id | INTEGER | 主鍵 |
| camera_id | VARCHAR(64) | 攝影機 ID |
| indicator_id | VARCHAR(64) | 指示燈 ID |
| state | BOOLEAN | 狀態（TRUE=亮起，FALSE=熄滅） |
| brightness | FLOAT | 亮度值（0-255）或顏色比例（0-100%） |
| timestamp | DATETIME | 讀取時間 |

## 常用查詢範例

### 查詢最新讀數

```sql
SELECT camera_id, meter_id, value, timestamp
FROM readings
WHERE timestamp > NOW() - INTERVAL '1 hour'
ORDER BY timestamp DESC;
```

### 查詢指示燈警報歷史

```sql
SELECT camera_id, indicator_id, state, timestamp
FROM indicator_readings
WHERE state = true
ORDER BY timestamp DESC
LIMIT 100;
```

### 統計每小時平均值

```sql
SELECT
    camera_id,
    meter_id,
    DATE_TRUNC('hour', timestamp) AS hour,
    AVG(value) AS avg_value,
    COUNT(*) AS reading_count
FROM readings
WHERE value IS NOT NULL
GROUP BY camera_id, meter_id, DATE_TRUNC('hour', timestamp)
ORDER BY hour DESC;
```

## 維護

### 手動清理舊資料

```sql
-- 刪除 30 天前的儀表讀數
DELETE FROM readings WHERE timestamp < NOW() - INTERVAL '30 days';

-- 刪除 30 天前的指示燈讀數
DELETE FROM indicator_readings WHERE timestamp < NOW() - INTERVAL '30 days';
```

### 備份資料庫

```bash
# 匯出
docker exec metereye-db pg_dump -U metereye metereye > backup.sql

# 匯入
cat backup.sql | docker exec -i metereye-db psql -U metereye metereye
```

### 停止與刪除

```bash
# 停止服務（保留資料）
docker compose down

# 停止服務並刪除資料（包含所有歷史記錄）
docker compose down -v
```

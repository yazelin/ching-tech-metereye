## Context

工廠火災警報面板（複合式受信總機）有多個區域燈號，正常時燈號熄滅，警報發生時燈號亮起（紅色）。需要偵測這些燈號的開/關狀態並記錄歷史。

參考圖片：
- `參考照片/現場拍/火災警報.jpg` - 正常狀態（燈號熄滅）
- `參考照片/現場拍/火災警報發生.png` - 警報狀態（燈號亮起）

## Goals / Non-Goals

**Goals:**
- 支援偵測單一燈號的 ON/OFF 狀態
- 與現有 meter 系統並行運作
- 共用相同的匯出管道（HTTP、MQTT、Database）
- 在 Dashboard 顯示燈號狀態

**Non-Goals:**
- 不支援燈號閃爍頻率偵測
- 不支援多色燈號狀態判斷（如：綠→黃→紅）
- 不做 OCR 辨識燈號旁的文字標籤

## Decisions

### 1. 資料模型設計
**Decision:** 新增獨立的 `IndicatorConfigData` 和 `IndicatorReading`，而非擴充 Meter。

**Rationale:** Meter 輸出是數值（float），Indicator 輸出是布林值。雖然可以用 Meter 的 value=1/0 表示，但語意不清且 confidence 計算方式不同。獨立模型更清晰。

### 2. 偵測演算法
**Decision:** 支援兩種模式：
1. **Brightness mode**: 計算 ROI 灰階平均值，與 threshold 比較
2. **Color mode**: 計算特定顏色在 HSV 空間的像素比例

**Rationale:**
- Brightness 適用於單色燈號（如紅色警報燈）
- Color 適用於需要區分顏色的場景（如紅/綠雙色燈）

### 3. 資料庫 Schema
**Decision:** 新增 `indicator_readings` 資料表，結構類似 `readings`：

```sql
CREATE TABLE indicator_readings (
    id INTEGER PRIMARY KEY,
    camera_id VARCHAR(64) NOT NULL,
    indicator_id VARCHAR(64) NOT NULL,
    state BOOLEAN NOT NULL,          -- ON=true, OFF=false
    brightness FLOAT,                -- 實際亮度值（debug 用）
    timestamp DATETIME NOT NULL,
    INDEX idx_camera_indicator_time (camera_id, indicator_id, timestamp)
);
```

**Rationale:** 獨立資料表避免與 meter readings 混用，查詢更直觀。

### 4. Config 結構
**Decision:** indicators 與 meters 並列於 camera 下：

```yaml
cameras:
  - id: cam-01
    meters: [...]
    indicators:
      - id: fire-west
        name: "西側PBL"
        perspective:
          points: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
          output_size: [width, height]
        detection:
          mode: brightness  # brightness | color
          threshold: 128    # 0=auto (Otsu)
          on_color: red     # color mode 專用
        show_on_dashboard: true
```

## Risks / Trade-offs

| Risk | Mitigation |
|------|------------|
| 環境光線變化影響偵測 | 提供 auto threshold (Otsu)；建議固定 ROI 避開反光 |
| 燈號閃爍造成誤判 | 可考慮加入 debounce 機制（連續 N 幀相同才更新） |
| 大量燈號增加 CPU 負載 | Indicator 偵測比 OCR 輕量許多，影響有限 |

## Open Questions

1. 是否需要支援「閃爍」狀態偵測？（目前只有 ON/OFF）
2. 是否需要支援警報觸發時發送通知（如 LINE、Email）？
3. 資料保留策略是否與 meter readings 相同？

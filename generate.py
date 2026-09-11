from pathlib import Path
from datetime import datetime, timezone
import csv
import io
import json
import time

import httpx


APP_VERSION = "1.0.3"

DATASET_ID = "54A507C4-C038-41B5-BF60-BBECB9D052C6"
CSV_URL = f"https://data.ntpc.gov.tw/api/datasets/{DATASET_ID}/csv/file"

OUTPUT_FILE = Path("docs/parking.json")

REQUEST_HEADERS = {
    "Accept": "text/csv,*/*;q=0.8",
    "User-Agent": "smart-parking-app/1.0.3",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
}


def field(row, *names):
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return ""


def decode_csv(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp950", "big5"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            pass

    raise RuntimeError("無法判斷政府 CSV 編碼")


def analyze_status(parking_status: str, cell_status: str):
    """
    將政府資料轉成前端顏色狀態。

    green   = 空白停車格
    red     = 已有停車
    gray    = 無法判讀

    若後續確認政府欄位定義不同，只需要調整這個函式。
    """

    candidates = [
        str(parking_status or "").strip().lower(),
        str(cell_status or "").strip().lower(),
    ]

    for value in candidates:
        if not value:
            continue

        # 常見布林 / 數值狀態
        if value in {"0", "n", "no", "false"}:
            return "empty", "空白停車格", "#22c55e"

        if value in {"1", "y", "yes", "true"}:
            return "occupied", "已有停車", "#ef4444"

        empty_keywords = (
            "空位",
            "空車位",
            "無車",
            "可停",
            "空車",
            "available",
            "empty",
            "vacant",
            "free",
        )

        occupied_keywords = (
            "有車",
            "已停",
            "占用",
            "佔用",
            "occupied",
            "full",
            "busy",
        )

        if any(keyword in value for keyword in empty_keywords):
            return "empty", "空白停車格", "#22c55e"

        if any(keyword in value for keyword in occupied_keywords):
            return "occupied", "已有停車", "#ef4444"

    return "unknown", "狀態未知", "#9ca3af"


def fetch_csv():
    timeout = httpx.Timeout(
        connect=20.0,
        read=90.0,
        write=20.0,
        pool=20.0,
    )

    last_error = None

    for attempt in range(1, 4):
        try:
            with httpx.Client(
                timeout=timeout,
                follow_redirects=True,
                headers=REQUEST_HEADERS,
            ) as client:
                response = client.get(CSV_URL)
                response.raise_for_status()
                return response.content

        except Exception as error:
            last_error = error

            if attempt < 3:
                time.sleep(attempt * 3)

    raise RuntimeError(f"政府停車資料下載失敗：{last_error}")


def normalize_rows(content: bytes):
    text = decode_csv(content)

    reader = csv.DictReader(io.StringIO(text))

    parking = []

    for raw in reader:
        lat_raw = field(
            raw,
            "latitude",
            "Latitude",
            "LATITUDE",
            "lat",
            "LAT",
            "定位坐標[緯度]",
            "定位坐標 [緯度]",
            "緯度",
        )

        lng_raw = field(
            raw,
            "longitude",
            "Longitude",
            "LONGITUDE",
            "lng",
            "lon",
            "LNG",
            "LON",
            "定位坐標[經度]",
            "定位坐標 [經度]",
            "經度",
        )

        try:
            lat = float(lat_raw)
            lng = float(lng_raw)
        except (TypeError, ValueError):
            continue

        # 新北 / 大台北附近的基本合理範圍
        if not (24.0 <= lat <= 26.0 and 120.0 <= lng <= 123.0):
            continue

        cell_status = field(
            raw,
            "cellstatus",
            "CELLSTATUS",
            "CellStatus",
            "車格狀態",
        )

        parking_status = field(
            raw,
            "parkingstatus",
            "ParkingStatus",
            "PARKINGSTATUS",
            "停車狀態",
        )

        status_key, status_label, marker_color = analyze_status(
            parking_status,
            cell_status,
        )

        parking.append(
            {
                "id": field(raw, "id", "ID", "系統編號"),
                "cellId": field(raw, "cellid", "CELLID", "CellID", "車格編號"),
                "name": field(raw, "name", "NAME", "類型"),
                "roadName": field(
                    raw,
                    "roadname",
                    "ROADNAME",
                    "RoadName",
                    "路段名稱",
                ),
                "day": field(raw, "day", "DAY", "開放停車日說明"),
                "hour": field(raw, "hour", "HOUR", "開放停車時間說明"),
                "pay": field(raw, "pay", "PAY", "收費方式"),
                "payCash": field(raw, "paycash", "PAYCASH", "收費計價"),
                "memo": field(raw, "memo", "MEMO", "備註"),
                "cellStatus": cell_status,
                "parkingStatus": parking_status,
                "statusKey": status_key,
                "statusLabel": status_label,
                "markerColor": marker_color,
                "lat": lat,
                "lng": lng,
            }
        )

    return parking


def main():
    content = fetch_csv()
    parking = normalize_rows(content)

    if not parking:
        raise RuntimeError("政府資料下載成功，但沒有可用停車格座標")

    payload = {
        "version": APP_VERSION,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "count": len(parking),
        "data": parking,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    OUTPUT_FILE.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    print(f"Generated {OUTPUT_FILE} with {len(parking)} parking spaces")


if __name__ == "__main__":
    main()

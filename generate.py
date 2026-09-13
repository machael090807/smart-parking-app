from __future__ import annotations

import argparse
import csv
import io
import json
import shutil
import tempfile
import zipfile

from datetime import datetime
from pathlib import Path

import requests
import shapefile
import ssl

from requests.adapters import HTTPAdapter
from pyproj import CRS
from pyproj import Transformer


# =========================================================
# 路徑
# =========================================================

ROOT_DIR = Path(__file__).resolve().parent

DOCS_DIR = ROOT_DIR / "docs"

DOCS_DIR.mkdir(
    parents=True,
    exist_ok=True
)


TAIPEI_JSON_PATH = (
    DOCS_DIR
    / "parking-taipei.json"
)


UNIFIED_JSON_PATH = (
    DOCS_DIR
    / "parking.json"
)


# =========================================================
# 新北市 API
# =========================================================

NTPC_DATASET_ID = (
    "54A507C4-C038-41B5-BF60-BBECB9D052C6"
)


NTPC_CSV_URL = (
    "https://data.ntpc.gov.tw/api/datasets/"
    f"{NTPC_DATASET_ID}/csv/file"
)


# =========================================================
# 台北市官方路邊停車格 SHP
# =========================================================

TAIPEI_RESOURCE_ID = (
    "7e2f32a0-9201-4666-a0ed-11034e6c2b66"
)


TAIPEI_DOWNLOAD_URLS = [

    (
        "https://data.taipei/api/frontstage/"
        "tpeod/dataset/resource.download"
        f"?rid={TAIPEI_RESOURCE_ID}"
    ),

    (
        "https://data.taipei/api/dataset/"
        "5a911ea5-1694-4301-808e-e1780d971611/"
        "resource/"
        f"{TAIPEI_RESOURCE_ID}/download"
    ),

]


# =========================================================
# 共用
# =========================================================

HEADERS = {

    "User-Agent":
        "Smart-Parking-App/1.1",

    "Accept":
        "*/*",

}

# =========================================================
# HTTPS 相容設定
# Python 3.13+ 對部分舊式憑證鏈檢查較嚴格
# 保留憑證驗證，只關閉 X509 STRICT
# =========================================================

class CompatibleTLSAdapter(HTTPAdapter):

    def init_poolmanager(
        self,
        connections,
        maxsize,
        block=False,
        **pool_kwargs
    ):

        context = ssl.create_default_context()

        if hasattr(
            ssl,
            "VERIFY_X509_STRICT"
        ):
            context.verify_flags &= (
                ~ssl.VERIFY_X509_STRICT
            )

        pool_kwargs[
            "ssl_context"
        ] = context

        return super().init_poolmanager(
            connections,
            maxsize,
            block=block,
            **pool_kwargs
        )


HTTP = requests.Session()

HTTP.mount(
    "https://",
    CompatibleTLSAdapter()
)

HTTP.headers.update(
    HEADERS
)


def now_iso():
    return (
        datetime.now()
        .astimezone()
        .isoformat(
            timespec="seconds"
        )
    )


def clean_string(value):

    if value is None:
        return ""

    return str(value).strip()


def get_value(
    row,
    *keys
):

    if not row:
        return ""

    lower_map = {

        str(key).lower():
            value

        for key, value
        in row.items()

    }

    for key in keys:

        if key in row:

            value = row[key]

            if (
                value is not None
                and
                str(value).strip()
            ):

                return value

        lower_key = (
            str(key)
            .lower()
        )

        if lower_key in lower_map:

            value = (
                lower_map[
                    lower_key
                ]
            )

            if (
                value is not None
                and
                str(value).strip()
            ):

                return value

    return ""


# =========================================================
# 新北市
# =========================================================

def normalize_ntpc_row(
    row
):

    latitude = clean_string(

        get_value(
            row,

            "latitude",
            "Latitude",
            "LATITUDE",

            "定位坐標[緯度]",
            "定位坐標 [緯度]",
            "緯度",
        )

    )


    longitude = clean_string(

        get_value(
            row,

            "longitude",
            "Longitude",
            "LONGITUDE",

            "定位坐標[經度]",
            "定位坐標 [經度]",
            "經度",
        )

    )


    try:

        lat_number = float(
            latitude
        )

        lng_number = float(
            longitude
        )

    except (
        TypeError,
        ValueError
    ):

        return None


    if not (
        24.0
        <= lat_number
        <= 26.0
        and
        120.0
        <= lng_number
        <= 123.0
    ):

        return None


    return {

        "id":
            clean_string(
                get_value(
                    row,
                    "id",
                    "ID",
                    "系統編號",
                )
            ),

        "cellid":
            clean_string(
                get_value(
                    row,
                    "cellid",
                    "CellID",
                    "CELLID",
                    "車格編號",
                )
            ),

        "name":
            clean_string(
                get_value(
                    row,
                    "name",
                    "NAME",
                    "類型",
                )
            ),

        "day":
            clean_string(
                get_value(
                    row,
                    "day",
                    "DAY",
                    "開放停車日說明",
                )
            ),

        "hour":
            clean_string(
                get_value(
                    row,
                    "hour",
                    "HOUR",
                    "開放停車時間說明",
                )
            ),

        "pay":
            clean_string(
                get_value(
                    row,
                    "pay",
                    "PAY",
                    "收費方式",
                )
            ),

        "paycash":
            clean_string(
                get_value(
                    row,
                    "paycash",
                    "PAYCASH",
                    "收費計價",
                )
            ),

        "memo":
            clean_string(
                get_value(
                    row,
                    "memo",
                    "MEMO",
                    "備註",
                )
            ),

        "roadid":
            clean_string(
                get_value(
                    row,
                    "roadid",
                    "ROADID",
                    "路段代碼",
                )
            ),

        "roadname":
            clean_string(
                get_value(
                    row,
                    "roadname",
                    "ROADNAME",
                    "路段名稱",
                )
            ),

        "cellstatus":
            clean_string(
                get_value(
                    row,
                    "cellstatus",
                    "CELLSTATUS",
                    "車格狀態",
                )
            ),

        "isnowcash":
            clean_string(
                get_value(
                    row,
                    "isnowcash",
                    "ISNOWCASH",
                    "紀錄現在有無收費",
                )
            ),

        "parkingstatus":
            clean_string(
                get_value(
                    row,
                    "parkingstatus",
                    "PARKINGSTATUS",
                    "停車狀態",
                )
            ),

        "latitude":
            lat_number,

        "longitude":
            lng_number,

        "countycode":
            clean_string(
                get_value(
                    row,
                    "countycode",
                    "COUNTYCODE",
                    "縣市代碼",
                )
            ),

        "areacode":
            clean_string(
                get_value(
                    row,
                    "areacode",
                    "AREACODE",
                    "鄉鎮代碼",
                )
            ),

        "city":
            "NewTaipei",

        "cityName":
            "新北市",

        "source":
            "ntpc",

    }


def fetch_new_taipei():

    print(
        "下載新北市即時停車資料..."
    )


    response = HTTP.get(

        NTPC_CSV_URL,

        headers=HEADERS,

        timeout=60,

    )


    response.raise_for_status()


    text = (
        response.content
        .decode(
            "utf-8-sig",
            errors="replace"
        )
    )


    reader = csv.DictReader(
        io.StringIO(
            text
        )
    )


    output = []


    for row in reader:

        item = normalize_ntpc_row(
            row
        )

        if item:

            output.append(
                item
            )


    print(
        f"新北市：{len(output):,} 格"
    )


    return output


# =========================================================
# 台北市車格種類
# =========================================================

TAIPEI_TYPE_NAMES = {

    "01": "小型車",

    "02": "機車",

    "03": "身心障礙專用汽車",

    "04": "身心障礙專用機車",

    "05": "警車",

    "06": "大型車",

    "07": "貨車裝卸專用",

    "08": "計程車",

    "09": "限時停車",

    "10": "時段性禁停汽車",

    "11": "機慢車停放區",

    "12": "公用汽車",

    "13": "公用機車",

    "14": "警用機車",

    "15": "汽車停車彎",

    "16":
        "機慢車停放區（警車）",

    "17": "消防車",

    "18":
        "機慢車停放區（身障）",

    "19": "時段禁停機車",

    "20": "限時停車機車",

    "21":
        "垃圾車專用（時段管制）",

    "22":
        "汽機車彈性共用",

    "23":
        "大客車與小型車共用",

}


# 目前 APP 主要先顯示汽車相關
# 暫時排除純機車車格

TAIPEI_EXCLUDED_MOTORCYCLE_TYPES = {

    "02",
    "04",
    "11",
    "13",
    "14",
    "16",
    "18",
    "19",
    "20",

}


# =========================================================
# 台北市下載
# =========================================================

def download_taipei_zip(
    destination
):

    last_error = None


    for url in TAIPEI_DOWNLOAD_URLS:

        try:

            print(
                "下載台北市 SHP..."
            )

            print(
                url
            )


            with HTTP.get(

                url,

                headers=HEADERS,

                timeout=180,

                stream=True,

                allow_redirects=True,

            ) as response:

                response.raise_for_status()


                with open(
                    destination,
                    "wb"
                ) as file:

                    for chunk in (
                        response.iter_content(
                            chunk_size=1024 * 1024
                        )
                    ):

                        if chunk:

                            file.write(
                                chunk
                            )


            if (
                destination.exists()
                and
                destination.stat().st_size
                > 1000
            ):

                return


        except Exception as error:

            last_error = error

            print(
                "下載失敗，嘗試下一個網址：",
                error
            )


    raise RuntimeError(
        "無法下載台北市停車格 SHP"
    ) from last_error


# =========================================================
# SHP 工具
# =========================================================

def choose_shapefile(
    directory
):

    candidates = list(
        directory.rglob(
            "*.shp"
        )
    )


    if not candidates:

        raise FileNotFoundError(
            "ZIP 內找不到 .shp"
        )


    return max(

        candidates,

        key=lambda path:
            path.stat().st_size

    )


def get_transformer(
    shp_path
):

    prj_path = (
        shp_path
        .with_suffix(
            ".prj"
        )
    )


    source_crs = None


    if prj_path.exists():

        try:

            prj_text = (
                prj_path
                .read_text(
                    encoding="utf-8",
                    errors="ignore"
                )
            )


            if prj_text.strip():

                source_crs = (
                    CRS.from_wkt(
                        prj_text
                    )
                )

        except Exception as error:

            print(
                "讀取 PRJ 失敗：",
                error
            )


    if source_crs is None:

        # 台北市 GIS 常見 TWD97 / TM2 121
        source_crs = CRS.from_epsg(
            3826
        )


    return Transformer.from_crs(

        source_crs,

        CRS.from_epsg(
            4326
        ),

        always_xy=True,

    )


def shape_center(
    shape
):

    if not shape.points:

        return None


    # Point 類型
    if len(shape.points) == 1:

        return (
            shape.points[0][0],
            shape.points[0][1],
        )


    try:

        bbox = shape.bbox

    except Exception:

        bbox = None


    if (
        bbox
        and
        len(bbox) >= 4
    ):

        x = (
            float(bbox[0])
            +
            float(bbox[2])
        ) / 2


        y = (
            float(bbox[1])
            +
            float(bbox[3])
        ) / 2


        return (
            x,
            y
        )


    x = sum(
        point[0]
        for point
        in shape.points
    ) / len(
        shape.points
    )


    y = sum(
        point[1]
        for point
        in shape.points
    ) / len(
        shape.points
    )


    return (
        x,
        y
    )


def open_shapefile(
    shp_path
):

    encodings = [

        "utf-8",

        "cp950",

        "big5",

    ]


    last_error = None


    for encoding in encodings:

        try:

            reader = shapefile.Reader(

                str(
                    shp_path
                ),

                encoding=encoding,

                encodingErrors="replace",

            )


            # 強制讀一筆，
            # 確認 DBF 可解析

            if len(reader) > 0:

                _ = reader.record(
                    0
                )


            print(
                f"DBF 編碼：{encoding}"
            )


            return reader


        except Exception as error:

            last_error = error


    raise RuntimeError(
        "無法讀取台北市 SHP"
    ) from last_error


# =========================================================
# 台北 SHP → JSON
# =========================================================

def convert_taipei_shp(
    shp_path
):

    reader = open_shapefile(
        shp_path
    )


    field_names = [

        field[0]

        for field
        in reader.fields[1:]

    ]


    transformer = get_transformer(
        shp_path
    )


    output = []


    for index, shape_record in enumerate(
        reader.iterShapeRecords()
    ):

        record = dict(

            zip(
                field_names,
                shape_record.record
            )

        )


        pktype = clean_string(

            get_value(
                record,
                "pktype"
            )

        ).zfill(2)


        # 排除純機車格

        if (
            pktype
            in
            TAIPEI_EXCLUDED_MOTORCYCLE_TYPES
        ):

            continue


        center = shape_center(
            shape_record.shape
        )


        if not center:

            continue


        x, y = center


        # 有些資料可能本身已經是經緯度

        if (
            119
            <= x
            <= 123
            and
            21
            <= y
            <= 26
        ):

            longitude = x

            latitude = y


        else:

            try:

                longitude, latitude = (
                    transformer.transform(
                        x,
                        y
                    )
                )

            except Exception:

                continue


        if not (
            24.5
            <= latitude
            <= 25.3
            and
            121.3
            <= longitude
            <= 121.8
        ):

            continue


        pkid = clean_string(

            get_value(
                record,
                "pkid",
                "keyid"
            )

        )


        if not pkid:

            pkid = str(
                index + 1
            )


        type_name = clean_string(

            get_value(
                record,
                "pktype1"
            )

        )


        if not type_name:

            type_name = (
                TAIPEI_TYPE_NAMES.get(
                    pktype,
                    "汽車停車位"
                )
            )


        road_name = clean_string(

            get_value(
                record,
                "roadname",
                "pkroad"
            )

        )


        rate = clean_string(

            get_value(
                record,
                "pkrate"
            )

        )


        parking_time = clean_string(

            get_value(
                record,
                "pktime"
            )

        )


        address = clean_string(

            get_value(
                record,
                "pkadrs"
            )

        )


        note = clean_string(

            get_value(
                record,
                "pknote"
            )

        )


        memo_parts = [

            value

            for value in [

                note,
                address,

            ]

            if value

        ]


        item = {

            "id":
                f"TPE-{pkid}",

            "cellid":
                pkid,

            "name":
                type_name,

            "day":
                "",

            "hour":
                parking_time,

            "pay":
                (
                    "依台北市路邊停車規定"
                    if rate
                    else
                    "未提供"
                ),

            "paycash":
                rate,

            "memo":
                "；".join(
                    memo_parts
                ),

            "roadid":
                clean_string(
                    get_value(
                        record,
                        "rdcode",
                        "pkroad"
                    )
                ),

            "roadname":
                road_name,

            # 台北此資料集沒有單格即時占用
            # 留空 → 前端會判斷成灰色 unknown

            "cellstatus":
                "",

            "isnowcash":
                "",

            "parkingstatus":
                "",

            "latitude":
                round(
                    float(latitude),
                    7
                ),

            "longitude":
                round(
                    float(longitude),
                    7
                ),

            "countycode":
                "63000",

            "areacode":
                clean_string(
                    get_value(
                        record,
                        "zone"
                    )
                ),

            "city":
                "Taipei",

            "cityName":
                "台北市",

            "source":
                "taipei-static",

        }


        output.append(
            item
        )


    reader.close()


    print(
        f"台北市：{len(output):,} 格"
    )


    return output


# =========================================================
# 更新台北資料
# =========================================================

def refresh_taipei():

    with tempfile.TemporaryDirectory() as temp:

        temp_path = Path(
            temp
        )


        zip_path = (
            temp_path
            / "taipei-parking.zip"
        )


        extract_path = (
            temp_path
            / "taipei-shp"
        )


        extract_path.mkdir(
            parents=True,
            exist_ok=True
        )


        download_taipei_zip(
            zip_path
        )


        if not zipfile.is_zipfile(
            zip_path
        ):

            raise RuntimeError(
                "下載內容不是有效 ZIP"
            )


        with zipfile.ZipFile(
            zip_path,
            "r"
        ) as zip_file:

            zip_file.extractall(
                extract_path
            )


        shp_path = choose_shapefile(
            extract_path
        )


        print(
            "使用 SHP：",
            shp_path.name
        )


        taipei_data = (
            convert_taipei_shp(
                shp_path
            )
        )


    write_json(

        TAIPEI_JSON_PATH,

        {

            "generatedAt":
                now_iso(),

            "city":
                "Taipei",

            "data":
                taipei_data,

        }

    )


    return taipei_data


def load_existing_taipei():

    if not TAIPEI_JSON_PATH.exists():

        return None


    try:

        with open(
            TAIPEI_JSON_PATH,
            "r",
            encoding="utf-8"
        ) as file:

            content = json.load(
                file
            )


        if isinstance(
            content,
            list
        ):

            return content


        if isinstance(
            content,
            dict
        ):

            data = content.get(
                "data"
            )


            if isinstance(
                data,
                list
            ):

                return data


    except Exception as error:

        print(
            "讀取既有台北資料失敗：",
            error
        )


    return None


# =========================================================
# 輸出
# =========================================================

def write_json(
    path,
    content
):

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(

            content,

            file,

            ensure_ascii=False,

            separators=(
                ",",
                ":"
            )

        )


    size_mb = (
        path.stat().st_size
        /
        1024
        /
        1024
    )


    print(
        f"輸出：{path}"
    )


    print(
        f"大小：{size_mb:.2f} MB"
    )


# =========================================================
# Main
# =========================================================

def main():

    parser = argparse.ArgumentParser()


    parser.add_argument(

        "--refresh-taipei",

        action="store_true",

        help=(
            "強制重新下載台北市 SHP"
        ),

    )


    args = parser.parse_args()


    print(
        "======================================"
    )

    print(
        "Smart Parking 資料產生器"
    )

    print(
        "======================================"
    )


    new_taipei_data = (
        fetch_new_taipei()
    )


    taipei_data = None


    if args.refresh_taipei:

        taipei_data = (
            refresh_taipei()
        )


    else:

        taipei_data = (
            load_existing_taipei()
        )


        if taipei_data is None:

            print(
                "找不到台北快照，首次自動下載..."
            )


            taipei_data = (
                refresh_taipei()
            )


        else:

            print(
                "使用現有台北快照："
                f"{len(taipei_data):,} 格"
            )


    all_data = [

        *new_taipei_data,

        *taipei_data,

    ]


    write_json(

        UNIFIED_JSON_PATH,

        {

            "generatedAt":
                now_iso(),

            "cities": [

                "NewTaipei",
                "Taipei",

            ],

            "data":
                all_data,

        }

    )


    print(
        "======================================"
    )

    print(
        f"合計：{len(all_data):,} 格"
    )

    print(
        "完成"
    )

    print(
        "======================================"
    )


if __name__ == "__main__":

    main()
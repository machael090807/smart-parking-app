from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
import csv
import io
import time
import asyncio


# =========================================================
# APP VERSION
# =========================================================

APP_VERSION = "1.0.2"


# =========================================================
# APP
# =========================================================

app = FastAPI(
    title="智慧路邊停車媒合 APP",
    version=APP_VERSION
)


# =========================================================
# 新北市政府路邊停車資料
# =========================================================

DATASET_ID = "54A507C4-C038-41B5-BF60-BBECB9D052C6"

BASE_URL = f"https://data.ntpc.gov.tw/api/datasets/{DATASET_ID}"

CSV_URL = f"{BASE_URL}/csv/file"

JSON_URL = f"{BASE_URL}/json"


# =========================================================
# CACHE
# =========================================================

CACHE_SECONDS = 120

parking_cache = {
    "updated_at": 0,
    "data": []
}


# =========================================================
# HTTP HEADERS
# =========================================================

REQUEST_HEADERS = {
    "Accept": "*/*",

    "User-Agent": (
        "Mozilla/5.0 "
        "(Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/153.0 Safari/537.36"
    ),

    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",

    "Cache-Control": "no-cache"
}


# =========================================================
# GOVERNMENT REQUEST
# =========================================================

async def request_government(
    url,
    params=None,
    verify_ssl=True
):

    timeout = httpx.Timeout(
        connect=15.0,
        read=60.0,
        write=15.0,
        pool=15.0
    )

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        verify=verify_ssl,
        headers=REQUEST_HEADERS
    ) as client:

        response = await client.get(
            url,
            params=params
        )

        response.raise_for_status()

        return response


# =========================================================
# CSV
# =========================================================

def decode_csv(content: bytes):

    encodings = [
        "utf-8-sig",
        "utf-8",
        "cp950",
        "big5"
    ]

    last_error = None

    for encoding in encodings:

        try:

            return content.decode(
                encoding
            )

        except Exception as error:

            last_error = error

    raise last_error


def parse_csv(content: bytes):

    text = decode_csv(
        content
    )

    reader = csv.DictReader(
        io.StringIO(text)
    )

    rows = []

    for raw in reader:

        row = {}

        for key, value in raw.items():

            if key is None:

                continue

            clean_key = str(
                key
            ).strip()

            clean_value = (
                ""
                if value is None
                else str(value).strip()
            )

            row[clean_key] = clean_value

        if row:

            rows.append(
                row
            )

    return rows


async def fetch_csv_data(
    verify_ssl=True
):

    response = await request_government(
        CSV_URL,
        verify_ssl=verify_ssl
    )

    rows = parse_csv(
        response.content
    )

    if not rows:

        raise RuntimeError(
            "CSV 沒有取得資料"
        )

    return rows


# =========================================================
# JSON
# =========================================================

def normalize_json_payload(
    payload
):

    if isinstance(
        payload,
        list
    ):

        return payload

    if isinstance(
        payload,
        dict
    ):

        possible_keys = [
            "data",
            "result",
            "records",
            "items"
        ]

        for key in possible_keys:

            value = payload.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                return value

    return []


async def fetch_json_data(
    verify_ssl=True
):

    all_rows = []

    page = 0

    page_size = 1000

    while True:

        response = await request_government(

            JSON_URL,

            params={
                "page": page,
                "size": page_size
            },

            verify_ssl=verify_ssl

        )

        payload = response.json()

        rows = normalize_json_payload(
            payload
        )

        if not rows:

            break

        all_rows.extend(
            rows
        )

        if len(
            rows
        ) < page_size:

            break

        page += 1

        if page > 100:

            raise RuntimeError(
                "政府 API 分頁異常"
            )

        await asyncio.sleep(
            0.08
        )

    if not all_rows:

        raise RuntimeError(
            "JSON API 無資料"
        )

    return all_rows


# =========================================================
# FETCH STRATEGY
# =========================================================

async def fetch_parking_from_government():

    errors = []

    try:

        data = await fetch_csv_data(
            verify_ssl=True
        )

        return data, "csv"

    except Exception as error:

        errors.append(
            f"CSV SSL: {error}"
        )

    try:

        data = await fetch_json_data(
            verify_ssl=True
        )

        return data, "json"

    except Exception as error:

        errors.append(
            f"JSON SSL: {error}"
        )

    try:

        data = await fetch_csv_data(
            verify_ssl=False
        )

        return data, "csv_fallback"

    except Exception as error:

        errors.append(
            f"CSV fallback: {error}"
        )

    try:

        data = await fetch_json_data(
            verify_ssl=False
        )

        return data, "json_fallback"

    except Exception as error:

        errors.append(
            f"JSON fallback: {error}"
        )

    raise RuntimeError(
        " | ".join(
            errors
        )
    )


# =========================================================
# ROUTES
# =========================================================

@app.get(
    "/",
    response_class=HTMLResponse
)
async def index():

    return HTML_PAGE


@app.get(
    "/api/health"
)
async def health():

    return {
        "success": True,
        "version": APP_VERSION
    }


@app.get(
    "/api/parking"
)
async def parking():

    now = time.time()

    if (
        parking_cache["data"]
        and
        now - parking_cache["updated_at"]
        < CACHE_SECONDS
    ):

        return {
            "success": True,
            "cached": True,
            "count": len(
                parking_cache["data"]
            ),
            "source": "cache",
            "data": parking_cache["data"]
        }

    try:

        data, source = (
            await fetch_parking_from_government()
        )

        parking_cache["data"] = data

        parking_cache["updated_at"] = now

        return {
            "success": True,
            "cached": False,
            "count": len(data),
            "source": source,
            "data": data
        }

    except Exception as error:

        if parking_cache["data"]:

            return {
                "success": True,
                "cached": True,
                "stale": True,
                "count": len(
                    parking_cache["data"]
                ),
                "source": "stale_cache",
                "data": parking_cache["data"]
            }

        return JSONResponse(
            status_code=502,
            content={
                "success": False,
                "error": "無法取得停車格資料",
                "detail": str(error)
            }
        )


# =========================================================
# HTML
# =========================================================

HTML_PAGE = r"""
<!DOCTYPE html>

<html lang="zh-TW">

<head>

<meta charset="UTF-8">

<meta
    name="viewport"
    content="
        width=device-width,
        initial-scale=1.0,
        maximum-scale=1.0,
        user-scalable=no
    "
>

<title>
智慧路邊停車媒合 APP
</title>


<link
    href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css"
    rel="stylesheet"
>


<script
    src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js">
</script>


<style>


/* =========================================================
   BASE
========================================================= */

* {

    box-sizing:
        border-box;

}


html,
body {

    margin:
        0;

    padding:
        0;

    width:
        100%;

    height:
        100%;

    overflow:
        hidden;

    font-family:

        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        "Noto Sans TC",
        sans-serif;

    background:
        #f5f5f5;

}


button,
input {

    font:
        inherit;

}


#app {

    position:
        relative;

    width:
        100%;

    height:
        100%;

    overflow:
        hidden;

}


#map {

    width:
        100%;

    height:
        100%;

}


/* =========================================================
   HAMBURGER
========================================================= */

.menu-button {

    position:
        absolute;

    top:
        18px;

    right:
        18px;

    z-index:
        30;

    width:
        48px;

    height:
        48px;

    border:
        none;

    border-radius:
        14px;

    background:
        rgba(
            255,
            255,
            255,
            0.96
        );

    box-shadow:
        0
        4px
        18px
        rgba(
            0,
            0,
            0,
            0.14
        );

    cursor:
        pointer;

    display:
        flex;

    align-items:
        center;

    justify-content:
        center;

}


.menu-button-lines {

    width:
        21px;

    display:
        flex;

    flex-direction:
        column;

    gap:
        5px;

}


.menu-button-lines span {

    width:
        100%;

    height:
        2px;

    border-radius:
        999px;

    background:
        #202124;

}


/* =========================================================
   MENU BACKDROP
========================================================= */

.menu-backdrop {

    position:
        absolute;

    inset:
        0;

    z-index:
        39;

    background:
        rgba(
            0,
            0,
            0,
            0.18
        );

    opacity:
        0;

    pointer-events:
        none;

    transition:
        opacity
        0.2s
        ease;

}


.menu-backdrop.open {

    opacity:
        1;

    pointer-events:
        auto;

}


/* =========================================================
   SIDE MENU
========================================================= */

.side-menu {

    position:
        absolute;

    top:
        0;

    right:
        0;

    bottom:
        0;

    z-index:
        40;

    width:
        min(
            340px,
            86vw
        );

    background:
        #ffffff;

    box-shadow:
        -8px
        0
        32px
        rgba(
            0,
            0,
            0,
            0.15
        );

    transform:
        translateX(
            105%
        );

    transition:
        transform
        0.25s
        ease;

    padding:
        22px;

    overflow-y:
        auto;

}


.side-menu.open {

    transform:
        translateX(
            0
        );

}


.menu-header {

    display:
        flex;

    align-items:
        center;

    justify-content:
        space-between;

    margin-bottom:
        26px;

}


.menu-title {

    font-size:
        20px;

    font-weight:
        800;

    color:
        #1f2937;

}


.menu-version {

    margin-top:
        3px;

    font-size:
        12px;

    color:
        #9ca3af;

}


.menu-close {

    width:
        38px;

    height:
        38px;

    border:
        0;

    border-radius:
        10px;

    background:
        #f3f4f6;

    font-size:
        22px;

    cursor:
        pointer;

    color:
        #444;

}


.menu-section-title {

    margin-bottom:
        10px;

    color:
        #6b7280;

    font-size:
        12px;

    font-weight:
        700;

    letter-spacing:
        0.06em;

}


.filter-list {

    display:
        flex;

    flex-direction:
        column;

    gap:
        8px;

}


.filter-item {

    min-height:
        54px;

    padding:
        10px
        12px;

    border:
        1px
        solid
        #eceff3;

    border-radius:
        13px;

    display:
        flex;

    align-items:
        center;

    gap:
        11px;

    cursor:
        pointer;

    transition:
        background
        0.15s
        ease;

}


.filter-item:hover {

    background:
        #f8f9fa;

}


.filter-item input {

    width:
        18px;

    height:
        18px;

    cursor:
        pointer;

}


.filter-dot {

    width:
        14px;

    height:
        14px;

    flex:
        0
        0
        14px;

    border-radius:
        50%;

    border:
        2px
        solid
        white;

    box-shadow:
        0
        0
        0
        1px
        rgba(
            0,
            0,
            0,
            0.10
        );

}


.filter-dot.green {

    background:
        #22c55e;

}


.filter-dot.red {

    background:
        #ef4444;

}


.filter-dot.gray {

    background:
        #9ca3af;

}


.filter-name {

    flex:
        1;

    font-size:
        14px;

    font-weight:
        650;

    color:
        #333;

}


.filter-count {

    min-width:
        24px;

    padding:
        3px
        7px;

    border-radius:
        999px;

    background:
        #f1f3f5;

    font-size:
        11px;

    text-align:
        center;

    color:
        #777;

}


.menu-actions {

    margin-top:
        16px;

    display:
        grid;

    grid-template-columns:
        1fr
        1fr;

    gap:
        9px;

}


.menu-action {

    height:
        42px;

    border:
        none;

    border-radius:
        11px;

    background:
        #f3f4f6;

    color:
        #333;

    font-weight:
        650;

    cursor:
        pointer;

}


/* =========================================================
   BOTTOM BAR
========================================================= */

.bottom-card {

    position:
        absolute;

    left:
        50%;

    bottom:
        18px;

    z-index:
        25;

    transform:
        translateX(
            -50%
        );

    width:
        min(
            calc(100% - 36px),
            720px
        );

    padding:
        12px;

    border-radius:
        18px;

    background:
        rgba(
            255,
            255,
            255,
            0.97
        );

    box-shadow:
        0
        8px
        32px
        rgba(
            0,
            0,
            0,
            0.16
        );

    backdrop-filter:
        blur(
            8px
        );

}


.bottom-main {

    display:
        flex;

    align-items:
        center;

    gap:
        12px;

}


.bottom-info {

    flex:
        1;

    min-width:
        0;

}


.bottom-count {

    color:
        #222;

    font-size:
        15px;

    font-weight:
        750;

    white-space:
        nowrap;

    overflow:
        hidden;

    text-overflow:
        ellipsis;

}


.bottom-status {

    margin-top:
        3px;

    color:
        #8a8f98;

    font-size:
        11px;

    white-space:
        nowrap;

    overflow:
        hidden;

    text-overflow:
        ellipsis;

}


.refresh-button {

    flex:
        0
        0
        auto;

    min-width:
        92px;

    height:
        44px;

    padding:
        0
        15px;

    border:
        none;

    border-radius:
        12px;

    background:
        #1677ff;

    color:
        #ffffff;

    font-size:
        14px;

    font-weight:
        700;

    cursor:
        pointer;

}


.refresh-button:disabled {

    opacity:
        0.55;

    cursor:
        not-allowed;

}


/* =========================================================
   LOCATION
========================================================= */

.user-dot {

    width:
        18px;

    height:
        18px;

    border-radius:
        50%;

    background:
        #1677ff;

    border:
        3px
        solid
        white;

    box-shadow:
        0
        0
        0
        4px
        rgba(
            22,
            119,
            255,
            0.25
        );

}


/* =========================================================
   POPUP
========================================================= */

.parking-popup {

    min-width:
        210px;

    font-size:
        13px;

    line-height:
        1.65;

}


.parking-title {

    margin-bottom:
        7px;

    font-size:
        17px;

    font-weight:
        800;

}


.parking-status-line {

    display:
        flex;

    align-items:
        center;

    gap:
        6px;

    margin-bottom:
        7px;

}


.popup-status-dot {

    width:
        10px;

    height:
        10px;

    border-radius:
        50%;

}


.row {

    margin:
        3px
        0;

}


.maplibregl-popup-content {

    border-radius:
        14px;

    padding:
        13px
        15px;

}


/* =========================================================
   HIDE BUILT IN MAP CONTROLS
========================================================= */

.maplibregl-ctrl-top-left {

    display:
        none
        !important;

}


.maplibregl-ctrl-top-right {

    display:
        none
        !important;

}


.maplibregl-ctrl-bottom-right {

    margin-bottom:
        92px;

}


/* =========================================================
   MOBILE
========================================================= */

@media (
    max-width:
    600px
) {


    .menu-button {

        top:
            12px;

        right:
            12px;

        width:
            44px;

        height:
            44px;

        border-radius:
            13px;

    }


    .side-menu {

        width:
            min(
                320px,
                88vw
            );

        padding:
            19px;

    }


    .bottom-card {

        bottom:
            max(
                10px,
                env(
                    safe-area-inset-bottom
                )
            );

        width:
            calc(
                100% - 20px
            );

        padding:
            10px;

        border-radius:
            16px;

    }


    .bottom-main {

        gap:
            8px;

    }


    .bottom-count {

        font-size:
            13px;

    }


    .bottom-status {

        font-size:
            10px;

    }


    .refresh-button {

        min-width:
            76px;

        height:
            42px;

        padding:
            0
            11px;

        font-size:
            13px;

    }


    .maplibregl-ctrl-bottom-right {

        margin-bottom:
            88px;

    }

}


/* =========================================================
   SMALL MOBILE
========================================================= */

@media (
    max-width:
    390px
) {


    .bottom-count {

        font-size:
            12px;

    }


    .refresh-button {

        min-width:
            68px;

        padding:
            0
            9px;

    }

}


/* =========================================================
   DESKTOP
========================================================= */

@media (
    min-width:
    1000px
) {


    .menu-button {

        top:
            22px;

        right:
            22px;

    }


    .bottom-card {

        bottom:
            24px;

    }

}


</style>

</head>


<body>


<div id="app">


    <div id="map"></div>



    <!-- ==================================================
         漢堡按鈕
    =================================================== -->

    <button
        id="menuButton"
        class="menu-button"
        type="button"
        aria-label="開啟篩選選單"
    >

        <div class="menu-button-lines">

            <span></span>
            <span></span>
            <span></span>

        </div>

    </button>



    <!-- ==================================================
         遮罩
    =================================================== -->

    <div
        id="menuBackdrop"
        class="menu-backdrop"
    ></div>



    <!-- ==================================================
         漢堡選單
    =================================================== -->

    <aside
        id="sideMenu"
        class="side-menu"
    >


        <div class="menu-header">


            <div>

                <div class="menu-title">
                    停車格篩選
                </div>

                <div class="menu-version">
                    智慧停車 APP v1.0.2
                </div>

            </div>


            <button
                id="menuClose"
                class="menu-close"
                type="button"
            >
                ×
            </button>


        </div>



        <div class="menu-section-title">

            顯示停車格狀態

        </div>



        <div class="filter-list">


            <label class="filter-item">


                <input
                    id="filterEmpty"
                    type="checkbox"
                    checked
                >


                <span
                    class="filter-dot green"
                ></span>


                <span class="filter-name">

                    空白停車格

                </span>


                <span
                    id="emptyCount"
                    class="filter-count"
                >
                    0
                </span>


            </label>



            <label class="filter-item">


                <input
                    id="filterOccupied"
                    type="checkbox"
                    checked
                >


                <span
                    class="filter-dot red"
                ></span>


                <span class="filter-name">

                    已有停車

                </span>


                <span
                    id="occupiedCount"
                    class="filter-count"
                >
                    0
                </span>


            </label>



            <label class="filter-item">


                <input
                    id="filterUnknown"
                    type="checkbox"
                    checked
                >


                <span
                    class="filter-dot gray"
                ></span>


                <span class="filter-name">

                    狀態未知

                </span>


                <span
                    id="unknownCount"
                    class="filter-count"
                >
                    0
                </span>


            </label>


        </div>



        <div class="menu-actions">


            <button
                id="selectAllButton"
                class="menu-action"
                type="button"
            >
                全部顯示
            </button>


            <button
                id="clearAllButton"
                class="menu-action"
                type="button"
            >
                全部隱藏
            </button>


        </div>


    </aside>



    <!-- ==================================================
         下方資訊 + 更新
    =================================================== -->

    <div class="bottom-card">


        <div class="bottom-main">


            <div class="bottom-info">


                <div
                    id="bottomCount"
                    class="bottom-count"
                >

                    正在準備停車格資料…

                </div>


                <div
                    id="bottomStatus"
                    class="bottom-status"
                >

                    APP v1.0.2

                </div>


            </div>



            <button
                id="reloadButton"
                class="refresh-button"
                type="button"
            >

                重新整理

            </button>


        </div>


    </div>


</div>


<script>


/* =========================================================
   CONFIG
========================================================= */

const APP_VERSION =
    "1.0.2";


const DEFAULT_CENTER = [

    121.4618,

    25.0114

];


const MIN_ZOOM =
    15;


const MAX_VISIBLE_MARKERS =
    1500;


const MAP_STYLE_URL =

    "https://tiles.openfreemap.org/styles/liberty";



/* =========================================================
   DOM
========================================================= */

const menuButton =
    document.getElementById(
        "menuButton"
    );


const menuClose =
    document.getElementById(
        "menuClose"
    );


const menuBackdrop =
    document.getElementById(
        "menuBackdrop"
    );


const sideMenu =
    document.getElementById(
        "sideMenu"
    );


const reloadButton =
    document.getElementById(
        "reloadButton"
    );


const bottomCount =
    document.getElementById(
        "bottomCount"
    );


const bottomStatus =
    document.getElementById(
        "bottomStatus"
    );


const filterEmpty =
    document.getElementById(
        "filterEmpty"
    );


const filterOccupied =
    document.getElementById(
        "filterOccupied"
    );


const filterUnknown =
    document.getElementById(
        "filterUnknown"
    );


const emptyCount =
    document.getElementById(
        "emptyCount"
    );


const occupiedCount =
    document.getElementById(
        "occupiedCount"
    );


const unknownCount =
    document.getElementById(
        "unknownCount"
    );


const selectAllButton =
    document.getElementById(
        "selectAllButton"
    );


const clearAllButton =
    document.getElementById(
        "clearAllButton"
    );



/* =========================================================
   STATE
========================================================= */

let parkingData = [];


let userMarker = null;


let loading =
    false;


let mapReady =
    false;


let styleSimplified =
    false;



/* =========================================================
   MAP
========================================================= */

const map =
    new maplibregl.Map({

        container:
            "map",

        style:
            MAP_STYLE_URL,

        center:
            DEFAULT_CENTER,

        zoom:
            16,

        pitch:
            0,

        bearing:
            0,

        minZoom:
            11,

        maxZoom:
            19,

        attributionControl:
            false,

        dragRotate:
            false,

        pitchWithRotate:
            false,

        touchPitch:
            false

    });



/*
  注意：
  這版刻意不加入 NavigationControl

  所以左上角：
  +
  -

  已經移除。
*/


map.addControl(

    new maplibregl.AttributionControl({

        compact:
            true

    }),

    "bottom-right"

);



/* =========================================================
   MENU
========================================================= */

function openMenu() {

    sideMenu.classList.add(
        "open"
    );

    menuBackdrop.classList.add(
        "open"
    );

}


function closeMenu() {

    sideMenu.classList.remove(
        "open"
    );

    menuBackdrop.classList.remove(
        "open"
    );

}


menuButton.addEventListener(

    "click",

    openMenu

);


menuClose.addEventListener(

    "click",

    closeMenu

);


menuBackdrop.addEventListener(

    "click",

    closeMenu

);


document.addEventListener(

    "keydown",

    event => {

        if (
            event.key ===
            "Escape"
        ) {

            closeMenu();

        }

    }

);



/* =========================================================
   COMMON
========================================================= */

function getValue(
    object,
    ...keys
) {

    for (
        const key
        of
        keys
    ) {

        const value =
            object[key];

        if (

            value !== undefined &&

            value !== null &&

            value !== ""

        ) {

            return value;

        }

    }

    return "";

}


function escapeHTML(
    value
) {

    return String(
        value
    )

    .replaceAll(
        "&",
        "&amp;"
    )

    .replaceAll(
        "<",
        "&lt;"
    )

    .replaceAll(
        ">",
        "&gt;"
    )

    .replaceAll(
        '"',
        "&quot;"
    )

    .replaceAll(
        "'",
        "&#039;"
    );

}



/* =========================================================
   MAP STYLE
   乾淨簡易地圖
========================================================= */

function simplifyMapStyle() {

    if (
        styleSimplified
    ) {

        return;

    }


    const style =
        map.getStyle();


    if (
        !style ||
        !style.layers
    ) {

        return;

    }


    for (
        const layer
        of
        style.layers
    ) {


        const id =
            String(
                layer.id ||
                ""
            )
            .toLowerCase();


        const sourceLayer =
            String(
                layer[
                    "source-layer"
                ] ||
                ""
            )
            .toLowerCase();


        const type =
            String(
                layer.type ||
                ""
            )
            .toLowerCase();


        const keyword =
            `${id} ${sourceLayer}`;



        /* ---------------------------------------------
           保留基本背景
        --------------------------------------------- */

        const isBackground =
            type ===
            "background";


        const isWater =
            /water|ocean|river|lake|stream|canal/
            .test(
                keyword
            );


        const isLand =
            (
                /landuse|landcover|park|grass|wood|forest|residential/
                .test(
                    keyword
                )
            )
            &&
            type !==
            "symbol"
            &&
            type !==
            "fill-extrusion";


        /* ---------------------------------------------
           建築只保留平面 fill
           不保留 3D
        --------------------------------------------- */

        const isBuilding =

            /building/
            .test(
                keyword
            )

            &&

            type ===
            "fill";


        /* ---------------------------------------------
           保留道路
        --------------------------------------------- */

        const isRoadGeometry =

            /road|street|highway|transport|bridge|tunnel|motorway|trunk|primary|secondary|tertiary|path/
            .test(
                keyword
            )

            &&

            (
                type ===
                "line"

                ||

                type ===
                "fill"
            );


        /* ---------------------------------------------
           保留路名
        --------------------------------------------- */

        const isRoadLabel =

            /road|street|highway|transport|bridge|tunnel|motorway|trunk|primary|secondary|tertiary/
            .test(
                keyword
            )

            &&

            type ===
            "symbol";


        /* ---------------------------------------------
           保留店家
        --------------------------------------------- */

        const isShopLabel =

            /poi|shop|store|amenity|commercial|retail|restaurant|cafe|food|bank|hospital|pharmacy|hotel/
            .test(
                keyword
            )

            &&

            type ===
            "symbol";


        const keep =

            isBackground ||

            isWater ||

            isLand ||

            isBuilding ||

            isRoadGeometry ||

            isRoadLabel ||

            isShopLabel;



        /*
          不管原本是不是 3D
          fill-extrusion 強制隱藏
        */

        if (
            type ===
            "fill-extrusion"
        ) {

            map.setLayoutProperty(
                layer.id,
                "visibility",
                "none"
            );

            continue;

        }



        map.setLayoutProperty(

            layer.id,

            "visibility",

            keep
            ? "visible"
            : "none"

        );

    }


    styleSimplified =
        true;

}



/* =========================================================
   STATUS
========================================================= */

function analyzeSingleStatus(
    value
) {

    if (
        value ===
        undefined
        ||
        value ===
        null
    ) {

        return null;

    }


    const raw =
        String(
            value
        )
        .trim();


    if (
        !raw
    ) {

        return null;

    }


    const normalized =
        raw.toLowerCase();



    /*
      數值狀態
    */

    if (
        [
            "0",
            "n",
            "no",
            "false"
        ]
        .includes(
            normalized
        )
    ) {

        return {

            key:
                "empty",

            label:
                "空白停車格",

            color:
                "#22c55e"

        };

    }


    if (
        [
            "1",
            "y",
            "yes",
            "true"
        ]
        .includes(
            normalized
        )
    ) {

        return {

            key:
                "occupied",

            label:
                "已有停車",

            color:
                "#ef4444"

        };

    }



    const emptyKeywords = [

        "空位",

        "空車位",

        "無車",

        "可停",

        "空車",

        "available",

        "empty",

        "vacant",

        "free"

    ];


    const occupiedKeywords = [

        "有車",

        "已停",

        "占用",

        "佔用",

        "occupied",

        "full",

        "busy"

    ];



    if (

        emptyKeywords.some(

            keyword =>

                normalized.includes(
                    keyword
                )

        )

    ) {

        return {

            key:
                "empty",

            label:
                "空白停車格",

            color:
                "#22c55e"

        };

    }


    if (

        occupiedKeywords.some(

            keyword =>

                normalized.includes(
                    keyword
                )

        )

    ) {

        return {

            key:
                "occupied",

            label:
                "已有停車",

            color:
                "#ef4444"

        };

    }


    return null;

}



function getParkingAvailability(
    parking
) {

    const candidates = [

        parking.parkingStatus,

        parking.cellStatus

    ];


    for (
        const candidate
        of
        candidates
    ) {

        const result =
            analyzeSingleStatus(
                candidate
            );


        if (
            result
        ) {

            return result;

        }

    }


    return {

        key:
            "unknown",

        label:
            "狀態未知",

        color:
            "#9ca3af"

    };

}



/* =========================================================
   NORMALIZE DATA
========================================================= */

function normalizeParking(
    raw
) {


    const lat =
        Number(

            getValue(

                raw,

                "latitude",
                "Latitude",
                "LATITUDE",

                "lat",
                "LAT",

                "定位坐標[緯度]",
                "定位坐標 [緯度]",
                "緯度"

            )

        );


    const lng =
        Number(

            getValue(

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
                "經度"

            )

        );



    if (

        !Number.isFinite(
            lat
        )

        ||

        !Number.isFinite(
            lng
        )

        ||

        lat === 0

        ||

        lng === 0

        ||

        lat < 24

        ||

        lat > 26

        ||

        lng < 120

        ||

        lng > 123

    ) {

        return null;

    }



    const parking = {


        id:
            String(

                getValue(

                    raw,

                    "id",

                    "ID",

                    "系統編號"

                )

            ),


        cellId:
            String(

                getValue(

                    raw,

                    "cellid",

                    "CELLID",

                    "CellID",

                    "車格編號"

                )

            ),


        name:
            String(

                getValue(

                    raw,

                    "name",

                    "NAME",

                    "類型"

                )

            ),


        roadName:
            String(

                getValue(

                    raw,

                    "roadname",

                    "ROADNAME",

                    "RoadName",

                    "路段名稱"

                )

            ),


        day:
            String(

                getValue(

                    raw,

                    "day",

                    "DAY",

                    "開放停車日說明"

                )

            ),


        hour:
            String(

                getValue(

                    raw,

                    "hour",

                    "HOUR",

                    "開放停車時間說明"

                )

            ),


        pay:
            String(

                getValue(

                    raw,

                    "pay",

                    "PAY",

                    "收費方式"

                )

            ),


        payCash:
            String(

                getValue(

                    raw,

                    "paycash",

                    "PAYCASH",

                    "收費計價"

                )

            ),


        memo:
            String(

                getValue(

                    raw,

                    "memo",

                    "MEMO",

                    "備註"

                )

            ),


        cellStatus:
            String(

                getValue(

                    raw,

                    "cellstatus",

                    "CELLSTATUS",

                    "CellStatus",

                    "車格狀態"

                )

            ),


        parkingStatus:
            String(

                getValue(

                    raw,

                    "parkingstatus",

                    "PARKINGSTATUS",

                    "ParkingStatus",

                    "停車狀態"

                )

            ),


        lat,

        lng

    };



    const availability =
        getParkingAvailability(
            parking
        );


    parking.markerColor =
        availability.color;


    parking.displayStatus =
        availability.label;


    parking.statusKey =
        availability.key;


    return parking;

}



/* =========================================================
   LOAD PARKING
========================================================= */

async function loadParking() {


    if (
        loading
    ) {

        return;

    }


    loading =
        true;


    reloadButton.disabled =
        true;


    reloadButton.textContent =
        "更新中…";


    bottomCount.textContent =
        "正在取得停車格資料…";


    bottomStatus.textContent =
        "資料更新中";


    try {


        const response =
            await fetch(

                "/api/parking",

                {

                    cache:
                        "no-store"

                }

            );


        const result =
            await response.json();



        if (

            !response.ok

            ||

            !result.success

        ) {

            throw new Error(

                result.detail

                ||

                result.error

                ||

                (
                    "HTTP " +
                    response.status
                )

            );

        }



        parkingData =

            result.data

            .map(
                normalizeParking
            )

            .filter(
                Boolean
            );



        bottomStatus.textContent =

            `已載入 ${parkingData.length.toLocaleString()} 個停車格 · v${APP_VERSION}`;



        renderParking();


    }

    catch (
        error
    ) {


        console.error(
            error
        );


        bottomCount.textContent =
            "目前無法取得停車格";


        bottomStatus.textContent =
            "錯誤：" +
            error.message;

    }

    finally {


        loading =
            false;


        reloadButton.disabled =
            false;


        reloadButton.textContent =
            "重新整理";

    }

}



/* =========================================================
   MAP SOURCE
========================================================= */

function ensureParkingSourceAndLayer() {


    if (
        !map.getSource(
            "parking-source"
        )
    ) {


        map.addSource(

            "parking-source",

            {

                type:
                    "geojson",

                data: {

                    type:
                        "FeatureCollection",

                    features:
                        []

                }

            }

        );

    }



    if (
        !map.getLayer(
            "parking-layer"
        )
    ) {


        map.addLayer({

            id:
                "parking-layer",

            type:
                "circle",

            source:
                "parking-source",

            paint: {


                "circle-radius":

                    [
                        "interpolate",
                        [
                            "linear"
                        ],
                        [
                            "zoom"
                        ],

                        14,
                        4,

                        16,
                        6,

                        18,
                        8
                    ],


                "circle-color":

                    [
                        "get",
                        "markerColor"
                    ],


                "circle-stroke-color":
                    "#ffffff",


                "circle-stroke-width":
                    2,


                "circle-opacity":
                    0.96

            }

        });

    }

}



/* =========================================================
   GEOJSON
========================================================= */

function buildFeatureCollection(
    list
) {


    return {

        type:
            "FeatureCollection",


        features:

            list.map(

                parking => (

                    {

                        type:
                            "Feature",


                        geometry: {

                            type:
                                "Point",

                            coordinates: [

                                parking.lng,

                                parking.lat

                            ]

                        },


                        properties: {

                            id:
                                parking.id ||
                                "",

                            cellId:
                                parking.cellId ||
                                "",

                            name:
                                parking.name ||
                                "",

                            roadName:
                                parking.roadName ||
                                "",

                            hour:
                                parking.hour ||
                                "",

                            pay:
                                parking.pay ||
                                "",

                            payCash:
                                parking.payCash ||
                                "",

                            cellStatus:
                                parking.cellStatus ||
                                "",

                            parkingStatus:
                                parking.parkingStatus ||
                                "",

                            displayStatus:
                                parking.displayStatus ||
                                "狀態未知",

                            statusKey:
                                parking.statusKey ||
                                "unknown",

                            markerColor:
                                parking.markerColor ||
                                "#9ca3af"

                        }

                    }

                )

            )

    };

}



/* =========================================================
   FILTER
========================================================= */

function getActiveFilters() {


    const filters =
        new Set();


    if (
        filterEmpty.checked
    ) {

        filters.add(
            "empty"
        );

    }


    if (
        filterOccupied.checked
    ) {

        filters.add(
            "occupied"
        );

    }


    if (
        filterUnknown.checked
    ) {

        filters.add(
            "unknown"
        );

    }


    return filters;

}



/* =========================================================
   COUNTS
========================================================= */

function updateFilterCounts(
    visible
) {


    const counts = {

        empty:
            0,

        occupied:
            0,

        unknown:
            0

    };


    visible.forEach(

        parking => {


            if (
                counts[
                    parking.statusKey
                ]
                !==
                undefined
            ) {


                counts[
                    parking.statusKey
                ] += 1;

            }

        }

    );


    emptyCount.textContent =
        counts.empty;


    occupiedCount.textContent =
        counts.occupied;


    unknownCount.textContent =
        counts.unknown;

}



/* =========================================================
   RENDER
========================================================= */

function renderParking() {


    if (

        !mapReady

        ||

        !map.getSource(
            "parking-source"
        )

    ) {

        return;

    }



    if (
        !parkingData.length
    ) {


        map
        .getSource(
            "parking-source"
        )
        .setData({

            type:
                "FeatureCollection",

            features:
                []

        });


        bottomCount.textContent =
            "目前沒有停車格資料";


        return;

    }



    const zoom =
        map.getZoom();



    if (
        zoom <
        MIN_ZOOM
    ) {


        map
        .getSource(
            "parking-source"
        )
        .setData({

            type:
                "FeatureCollection",

            features:
                []

        });


        bottomCount.textContent =
            "請放大地圖查看停車格";


        return;

    }



    const bounds =
        map.getBounds();



    /*
      目前視野所有停車格
    */

    const visibleAll =

        parkingData.filter(

            parking =>

                bounds.contains(

                    [

                        parking.lng,

                        parking.lat

                    ]

                )

        );



    updateFilterCounts(
        visibleAll
    );



    /*
      套用篩選
    */

    const activeFilters =
        getActiveFilters();



    const filtered =

        visibleAll.filter(

            parking =>

                activeFilters.has(
                    parking.statusKey
                )

        );



    const list =
        filtered.slice(

            0,

            MAX_VISIBLE_MARKERS

        );



    map
    .getSource(
        "parking-source"
    )
    .setData(

        buildFeatureCollection(
            list
        )

    );



    if (
        visibleAll.length === 0
    ) {


        bottomCount.textContent =
            "目前畫面內沒有停車格";


    }

    else if (
        filtered.length ===
        visibleAll.length
    ) {


        bottomCount.textContent =

            `目前畫面內有 ${visibleAll.length.toLocaleString()} 個停車格`;


    }

    else {


        bottomCount.textContent =

            `目前顯示 ${filtered.length.toLocaleString()} / ${visibleAll.length.toLocaleString()} 個停車格`;

    }

}



/* =========================================================
   POPUP
========================================================= */

function showParkingPopup(
    feature
) {


    const p =
        feature.properties ||
        {};


    const statusColor =
        p.markerColor ||
        "#9ca3af";


    const popupHTML = `

        <div class="parking-popup">


            <div class="parking-title">

                路邊停車格

            </div>


            <div class="parking-status-line">


                <span
                    class="popup-status-dot"
                    style="
                        background:
                        ${escapeHTML(
                            statusColor
                        )}
                    "
                >
                </span>


                <strong>

                    ${escapeHTML(
                        p.displayStatus ||
                        "狀態未知"
                    )}

                </strong>


            </div>


            <div class="row">

                車格編號：

                <strong>

                    ${escapeHTML(

                        p.cellId

                        ||

                        p.id

                        ||

                        "未提供"

                    )}

                </strong>

            </div>


            <div class="row">

                路段：

                ${escapeHTML(

                    p.roadName

                    ||

                    "未提供"

                )}

            </div>


            <div class="row">

                類型：

                ${escapeHTML(

                    p.name

                    ||

                    "未提供"

                )}

            </div>


            <div class="row">

                收費方式：

                ${escapeHTML(

                    p.pay

                    ||

                    "未提供"

                )}

            </div>


            <div class="row">

                收費：

                ${escapeHTML(

                    p.payCash

                    ||

                    "未提供"

                )}

            </div>


            <div class="row">

                收費時間：

                ${escapeHTML(

                    p.hour

                    ||

                    "未提供"

                )}

            </div>


        </div>

    `;



    new maplibregl.Popup({

        closeButton:
            true,

        closeOnClick:
            true,

        offset:
            12

    })

    .setLngLat(

        feature
        .geometry
        .coordinates

    )

    .setHTML(
        popupHTML
    )

    .addTo(
        map
    );

}



/* =========================================================
   GPS
========================================================= */

function setUserLocation(
    lng,
    lat
) {


    if (
        userMarker
    ) {

        userMarker.remove();

    }


    const element =
        document.createElement(
            "div"
        );


    element.className =
        "user-dot";


    userMarker =

        new maplibregl.Marker({

            element:
                element,

            anchor:
                "center"

        })

        .setLngLat(

            [
                lng,
                lat
            ]

        )

        .setPopup(

            new maplibregl.Popup({

                offset:
                    16

            })

            .setText(

                "你的目前位置"

            )

        )

        .addTo(
            map
        );

}



function locateUser() {


    if (
        !navigator.geolocation
    ) {


        map.setCenter(
            DEFAULT_CENTER
        );


        return;

    }



    navigator.geolocation.getCurrentPosition(


        position => {


            const lat =
                position
                .coords
                .latitude;


            const lng =
                position
                .coords
                .longitude;



            setUserLocation(

                lng,

                lat

            );


            map.jumpTo({

                center: [

                    lng,

                    lat

                ],

                zoom:
                    16,

                pitch:
                    0,

                bearing:
                    0

            });


            renderParking();

        },


        () => {


            map.jumpTo({

                center:
                    DEFAULT_CENTER,

                zoom:
                    16,

                pitch:
                    0,

                bearing:
                    0

            });


            renderParking();

        },


        {

            enableHighAccuracy:
                true,

            timeout:
                10000,

            maximumAge:
                0

        }

    );

}



/* =========================================================
   FILTER EVENTS
========================================================= */

[
    filterEmpty,
    filterOccupied,
    filterUnknown
]
.forEach(

    checkbox => {


        checkbox.addEventListener(

            "change",

            renderParking

        );

    }

);



selectAllButton.addEventListener(

    "click",

    () => {


        filterEmpty.checked =
            true;


        filterOccupied.checked =
            true;


        filterUnknown.checked =
            true;


        renderParking();

    }

);



clearAllButton.addEventListener(

    "click",

    () => {


        filterEmpty.checked =
            false;


        filterOccupied.checked =
            false;


        filterUnknown.checked =
            false;


        renderParking();

    }

);



/* =========================================================
   REFRESH
========================================================= */

reloadButton.addEventListener(

    "click",

    loadParking

);



/* =========================================================
   MAP EVENTS
========================================================= */

map.on(

    "load",

    () => {


        simplifyMapStyle();


        ensureParkingSourceAndLayer();


        mapReady =
            true;



        /*
          點擊停車格
        */

        map.on(

            "click",

            "parking-layer",

            event => {


                const feature =

                    event.features

                    &&

                    event.features[0];


                if (
                    feature
                ) {


                    showParkingPopup(
                        feature
                    );

                }

            }

        );



        map.on(

            "mouseenter",

            "parking-layer",

            () => {


                map
                .getCanvas()
                .style
                .cursor =
                    "pointer";

            }

        );



        map.on(

            "mouseleave",

            "parking-layer",

            () => {


                map
                .getCanvas()
                .style
                .cursor =
                    "";

            }

        );



        locateUser();


        loadParking();

    }

);



map.on(

    "moveend",

    renderParking

);



map.on(

    "zoomend",

    renderParking

);



map.on(

    "error",

    event => {


        console.warn(

            "地圖錯誤：",

            event

        );

    }

);


</script>


</body>

</html>
"""


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    import uvicorn

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000
    )